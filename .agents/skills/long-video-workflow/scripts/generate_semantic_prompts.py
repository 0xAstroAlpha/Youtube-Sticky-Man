import argparse
import json
import os
import re
import sys
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# Force UTF-8 stdout so Unicode chars don't crash on Windows subprocess pipes
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# --- Constants ---
CONTINUITY_PREFIX = (
    "Continuity instruction: use the scene_previous reference as the prior animation beat. "
    "Preserve character identity, camera distance, visual scale, white background, and line weight. "
)
BASE_TEMPLATE = (
    "Hand-drawn 2D doodle cartoon animation, flat colors, bold black outlines, "
    "slightly imperfect sketchy marker lines, {visual}, stark white background, no gradients, "
    "no shadows, no textures, no photorealism, no 3D, 16:9 aspect ratio, "
    "educational YouTube explainer doodle style."
)
MAIN_CHARACTER_DESC = "a primitive prehistoric male stick figure wearing animal skins"
PREEMPT_OFFSET = 0.1       # seconds — cut visual slightly before word is spoken
LONG_SCENE_THRESHOLD = 8.0   # seconds — threshold for Surgery warnings
MAX_SCENE_DURATION   = 4.0   # seconds — hard cap; auto-fill kicks in above this
COVERAGE_GAP_THRESHOLD = 2.0  # seconds — min uncovered end gap before inserting fill


def build_compact_word_index(words_data):
    """
    Serialize words to a compact array-of-arrays to minimise tokens.
    Format: [[index, word, start_s, end_s], ...]
    """
    return [[i, w['word'], round(w['start'], 3), round(w['end'], 3)]
            for i, w in enumerate(words_data)]


def generate_prompts(chunk_index, transcript_path):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env")
        return

    model_id = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-preview")
    print(f"[MODEL] Using {model_id}")

    with open(transcript_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    raw_text = data['text']
    text_content = re.sub(r'\[.*?\]', '', raw_text).strip()
    words_data = data['words']
    total_words = len(words_data)
    audio_end = words_data[-1]['end']

    # --- Dynamic scene count: ~70-80 chars/scene, also bounded by audio duration ---
    char_count = len(text_content)
    target_scenes = max(10, round(char_count / 75))
    # Guarantee at least 1 scene per MAX_SCENE_DURATION seconds of audio
    audio_min     = max(8, round(audio_end / MAX_SCENE_DURATION))
    min_scenes    = max(audio_min, round(char_count / 90))
    max_scenes    = max(target_scenes + 5, round(char_count / 60))
    print(f"[PLAN] {char_count} chars | {total_words} words | {audio_end:.1f}s audio -> target {target_scenes} scenes ({min_scenes}-{max_scenes})")

    # --- Build compact word index for Gemini (Level 1: direct index, no text matching) ---
    word_index = build_compact_word_index(words_data)
    word_index_json = json.dumps(word_index, ensure_ascii=False, separators=(',', ':'))

    client = genai.Client(api_key=api_key)

    sys_instruction = f"""You are an expert director for an educational YouTube doodle animation channel.
You receive spoken words with precise timestamps as arrays: [word_index, word, start_seconds, end_seconds].

Your task: plan a sequence of visual scenes for a doodle animation. For each scene output the word_index (wi) where the visual CUT should happen, describe the visual, and indicate continuity.

CRITICAL RULES:
1. Cover ALL words from index 0 to {total_words - 1}. Every moment of audio must map to a visual.
2. Output between {min_scenes} and {max_scenes} scenes (target: {target_scenes}). Aim for a new cut roughly every 3–5 words.
3. wi values MUST be strictly ascending integers. No duplicates. Valid range: 0 to {total_words - 1}.
4. TIMING HARD CAP — MOST IMPORTANT: The input gives you exact start_seconds for every word. Look at consecutive wi choices you plan to make. If the time gap between two consecutive wi entries would exceed {MAX_SCENE_DURATION} seconds, you MUST insert at least one extra cut in between. No scene may last longer than {MAX_SCENE_DURATION} seconds.
5. Character Lock: Use exact string "[MC]" for the main character. Example: "[MC] looking surprised".
6. Red X Rule: Use a giant bold red X ONLY for rejected/forbidden concepts. Not as decoration.
7. Do NOT include styling boilerplate (e.g. "Hand-drawn 2D doodle...") in "visual". Only describe the scene/action.
8. Enumeration Rule: Each item in a list MUST become its own separate scene.
9. cont (boolean): true = this scene directly continues the same visual action from the previous one (same location, same character doing related action). false = new concept or setting.

OUTPUT — strictly valid JSON array only, no extra text:
[
  {{"wi": 0, "visual": "scene description", "cont": false}},
  {{"wi": 4, "visual": "next scene", "cont": true}}
]"""

    print("Calling Gemini API (single pass -- direct word-index mode)...")
    response = client.models.generate_content(
        model=model_id,
        contents=word_index_json,
        config=types.GenerateContentConfig(
            system_instruction=sys_instruction,
            response_mime_type="application/json",
            max_output_tokens=32768,
            temperature=1.0,
            safety_settings=[
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,       threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,         threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,  threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,  threshold=types.HarmBlockThreshold.BLOCK_NONE),
            ]
        )
    )

    try:
        raw_resp = response.text.strip()
        if raw_resp.endswith("]\n]") or raw_resp.endswith("]]"):
            raw_resp = raw_resp.rsplit(']', 1)[0].strip()
            if not raw_resp.endswith(']'):
                raw_resp += ']'
        semantic_map = json.loads(raw_resp)
    except json.JSONDecodeError:
        print("Error: Failed to parse Gemini response as JSON.")
        print(response.text)
        return

    print(f"Gemini returned {len(semantic_map)} scenes. Validating indices...")

    # --- Level 1: Direct index lookup — zero miss rate ---
    compiled_shots = []
    last_wi = -1
    invalid_count = 0

    for shot in semantic_map:
        wi = shot.get('wi')
        visual = shot.get('visual', '')
        cont = bool(shot.get('cont', False))

        # Validate: must be int, in bounds, strictly ascending
        if not isinstance(wi, int) or wi < 0 or wi >= total_words:
            print(f"[SKIP] wi={wi!r} out of bounds (0-{total_words - 1}). Dropped.")
            invalid_count += 1
            continue
        if wi <= last_wi:
            print(f"[SKIP] wi={wi} not ascending (prev={last_wi}). Dropped.")
            invalid_count += 1
            continue

        compiled_shots.append({
            "wi":    wi,
            "visual": visual,
            "cont":  cont,
            "start": words_data[wi]['start'],
        })
        last_wi = wi

    if not compiled_shots:
        print("Error: No valid scenes after validation.")
        return

    print(f"[SUMMARY] Accepted {len(compiled_shots)}/{len(semantic_map)} scenes. Skipped {invalid_count} invalid.")

    # ANCHOR FIX: first image starts exactly when audio starts
    compiled_shots[0]['start'] = 0.0

    # PREEMPT FIX: cut visuals 100 ms before the target word is spoken
    for i in range(1, len(compiled_shots)):
        compiled_shots[i]['start'] = max(0.0, compiled_shots[i]['start'] - PREEMPT_OFFSET)

    # --- AUTO-FILL: inject midpoint cuts for any gap > MAX_SCENE_DURATION (pure Python, zero API cost) ---
    auto_fills = 0
    i = 0
    while i < len(compiled_shots) - 1:
        curr_start = compiled_shots[i]['start']
        next_start = compiled_shots[i + 1]['start']
        gap = next_start - curr_start

        if gap > MAX_SCENE_DURATION:
            mid_time = curr_start + gap / 2
            curr_wi  = compiled_shots[i].get('wi', 0)
            next_wi  = compiled_shots[i + 1].get('wi', total_words)

            # Find the word closest to mid_time within the gap window
            best_wi, best_dist = None, float('inf')
            for scan_wi in range(curr_wi + 1, next_wi):
                dist = abs(words_data[scan_wi]['start'] - mid_time)
                if dist < best_dist:
                    best_dist, best_wi = dist, scan_wi

            if best_wi is not None:
                fill_start = max(0.0, words_data[best_wi]['start'] - PREEMPT_OFFSET)
                fill_shot = {
                    "wi":     best_wi,
                    "visual": compiled_shots[i]['visual'],   # extend previous visual
                    "cont":   True,
                    "start":  fill_start,
                }
                compiled_shots.insert(i + 1, fill_shot)
                auto_fills += 1
                print(f"[AUTO-FILL] Gap {gap:.2f}s between scenes {i+1}<->{i+2} -> inserted fill at wi={best_wi} ({fill_start:.2f}s)")
                # Do NOT increment i; re-check the new (possibly still large) first half
            else:
                i += 1  # no word found in gap (shouldn't happen), move on
        else:
            i += 1

    if auto_fills:
        print(f"[AUTO-FILL] Total: {auto_fills} fill scene(s) injected. New total: {len(compiled_shots)} scenes.")

    # Compute end / duration for each shot (after auto-fill)
    for i, shot in enumerate(compiled_shots):
        if i < len(compiled_shots) - 1:
            end = compiled_shots[i + 1]['start']
        else:
            end = audio_end
        duration = round(end - shot['start'], 3)
        shot['end'] = end
        shot['duration'] = duration

        if duration > LONG_SCENE_THRESHOLD:
            word_str = words_data[shot['wi']]['word']
            print(f"[WARNING] Scene {i+1} wi={shot['wi']} ('{word_str}') is {duration:.2f}s. Consider Surgery.")

    # --- Level 2.2: Coverage validation — fill end gap ---
    last_end = compiled_shots[-1]['end']
    end_gap = round(audio_end - last_end, 3)
    if end_gap > COVERAGE_GAP_THRESHOLD:
        print(f"[COVERAGE] {end_gap:.2f}s uncovered at audio end. Inserting fill scene with last visual.")
        fill = {
            "wi":       total_words - 1,
            "visual":   compiled_shots[-1]['visual'],
            "cont":     True,
            "start":    last_end,
            "end":      audio_end,
            "duration": end_gap,
        }
        compiled_shots.append(fill)
        print(f"[COVERAGE] Fill scene: {last_end:.2f}s -> {audio_end:.2f}s")

    # --- Build final prompt objects ---
    prompts = []
    for i, shot in enumerate(compiled_shots):
        visual_desc = shot['visual'].replace("[MC]", MAIN_CHARACTER_DESC)
        styled_visual = BASE_TEMPLATE.format(visual=visual_desc)

        # Level 2.1: Inject continuity instruction for continuation scenes
        if shot['cont'] and i > 0:
            full_prompt = CONTINUITY_PREFIX + styled_visual
        else:
            full_prompt = styled_visual

        prompts.append({
            "order":           i + 1,
            "shot_id":         i + 1,
            "visual_kind":     "illustration",
            "generation_mode": "create",
            "visual_recipe":   "doodle-prehistoric-male",
            "timing": {
                "start":    shot['start'],
                "end":      shot['end'],
                "duration": shot['duration'],
            },
            "output": {
                "file":   f"{(i + 1):03d}.png",
                "format": "png",
            },
            "refs":   [],
            "prompt": full_prompt,
        })

    # --- Save outputs ---
    output_dir = os.path.dirname(transcript_path) or "."
    txt_path   = os.path.join(output_dir, f"prompts_chunk_{chunk_index}.txt")
    json_path  = os.path.join(output_dir, f"image_prompts_chunk_{chunk_index}.json")
    images_dir = os.path.join(output_dir, f"images_chunk_{chunk_index}")

    if not os.path.exists(images_dir):
        os.makedirs(images_dir)
        print(f"Created image directory: {images_dir}")

    with open(txt_path, 'w', encoding='utf-8') as f:
        for p in prompts:
            f.write(f"[{p['timing']['start']}-{p['timing']['end']}] {p['prompt']}\n")

    out_data = {
        "schema":         "sticky-man.prompt-pack.v1",
        "chunk_index":    chunk_index,
        "shot_count":     len(prompts),
        "total_duration": prompts[-1]['timing']['end'] if prompts else 0,
        "instructions": {
            "order":  "Create images in ascending order.",
            "output": "Return files using each item.output.path or file.",
            "refs":   "Use refs[] when the image tool supports reference images.",
        },
        "prompts": prompts,
    }

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(out_data, f, indent=2, ensure_ascii=False)

    print(f"[DONE] Compilation complete -> {output_dir} | {len(prompts)} scenes | {audio_end:.2f}s covered.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--chunk',      type=int, required=True, help='Chunk index')
    parser.add_argument('--transcript', type=str, required=True, help='Path to transcript JSON')
    args = parser.parse_args()
    generate_prompts(args.chunk, args.transcript)
