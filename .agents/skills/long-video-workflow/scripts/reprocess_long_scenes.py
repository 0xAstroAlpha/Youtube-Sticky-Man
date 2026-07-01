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


# --- Constants (must match generate_semantic_prompts.py) ---
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
PREEMPT_OFFSET = 0.1
LONG_SCENE_THRESHOLD = 8.0


def build_segment_index(words_data, seg_start_abs, seg_end_abs):
    """
    Extract words that belong to this time segment and return:
    - A compact word index relative to the segment: [[rel_idx, word, start, end], ...]
    - The absolute start index in words_data (for direct lookup later)
    """
    segment_words = [
        (abs_i, w) for abs_i, w in enumerate(words_data)
        if w['start'] >= seg_start_abs - 0.25 and w['end'] <= seg_end_abs + 0.25
    ]
    compact = [
        [rel_i, w['word'], round(w['start'], 3), round(w['end'], 3)]
        for rel_i, (_, w) in enumerate(segment_words)
    ]
    abs_offset = segment_words[0][0] if segment_words else 0
    return compact, abs_offset, segment_words


def reprocess_surgery(chunk_index, project_dir):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env")
        return

    model_id = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-preview")
    print(f"[MODEL] Using {model_id} for surgery batch")

    client = genai.Client(api_key=api_key)

    transcript_path  = os.path.join(project_dir, f"transcript_chunk_{chunk_index}.json")
    prompts_json_path = os.path.join(project_dir, f"image_prompts_chunk_{chunk_index}.json")

    if not os.path.exists(prompts_json_path):
        print(f"Error: {prompts_json_path} not found.")
        return

    with open(transcript_path, 'r', encoding='utf-8') as f:
        transcript_data = json.load(f)
    words_data = transcript_data['words']

    with open(prompts_json_path, 'r', encoding='utf-8') as f:
        prompts_data = json.load(f)

    old_prompts = prompts_data.get('prompts', [])

    # -------------------------------------------------------
    # PASS 1: Identify ALL long scenes and build batch payload
    # -------------------------------------------------------
    long_scenes = []   # list of {"scene_idx", "prompt_obj", "compact_words", "abs_offset", "seg_words"}

    for idx, p in enumerate(old_prompts):
        duration = float(p['timing']['duration'])
        if duration <= LONG_SCENE_THRESHOLD:
            continue

        start = float(p['timing']['start'])
        end   = float(p['timing']['end'])

        # Undo PREEMPT for accurate word extraction
        real_start = (start + PREEMPT_OFFSET) if idx > 0 else start

        compact, abs_offset, seg_words = build_segment_index(words_data, real_start, end)

        if not compact:
            print(f"[ERROR] Scene {idx+1}: no words found in [{real_start:.2f}s, {end:.2f}s]. Skipping.")
            continue

        seg_text = " ".join(w['word'] for _, w in seg_words)
        n_words  = len(compact)
        print(f"[SURGERY] Scene {idx+1} is {duration:.2f}s long → {n_words} words: \"{seg_text[:80]}{'...' if len(seg_text) > 80 else ''}\"")

        long_scenes.append({
            "scene_idx":    idx,
            "prompt_obj":   p,
            "compact_words": compact,
            "abs_offset":   abs_offset,
            "seg_words":    seg_words,
            "seg_end":      end,
        })

    if not long_scenes:
        print("[INFO] No scenes > 8.0s found. Everything is optimal.")
        return

    print(f"\n[BATCH] Sending {len(long_scenes)} long scene(s) to Gemini in a single call...")

    # -------------------------------------------------------
    # PASS 2: ONE batch Gemini call for all long scenes
    # -------------------------------------------------------
    # Input format: array of segments, each with scene_id + words
    batch_input = [
        {
            "scene_id": ls["scene_idx"],
            "words": ls["compact_words"],
        }
        for ls in long_scenes
    ]
    batch_input_json = json.dumps(batch_input, ensure_ascii=False, separators=(',', ':'))

    sys_instruction = f"""You are an expert director performing micro-surgery on an educational YouTube doodle animation.
You receive a batch of over-long scenes that each need to be split into 2–3 tighter sub-scenes.

Each segment contains:
- "scene_id": the original scene identifier (keep it in your output)
- "words": [[rel_index, word, start_seconds, end_seconds], ...]
  rel_index is relative to that segment only (starts at 0 for each segment).

For EACH segment, split it into 2–3 sub-scenes by choosing word indices (wi) where cuts happen.

RULES:
1. wi values must be in strictly ascending order within each segment.
2. wi must be a valid relative index for that segment's words array.
3. The first wi of each segment SHOULD be 0 (start of segment).
4. Character Lock: Use "[MC]" for the main character.
5. Red X Rule: Only for rejected/forbidden concepts.
6. Do NOT include styling boilerplate in "visual".
7. cont: true if this sub-scene directly continues the previous one visually.

OUTPUT — strictly valid JSON array, one object per input segment:
[
  {{
    "scene_id": <int>,
    "cuts": [
      {{"wi": 0, "visual": "description", "cont": false}},
      {{"wi": 3, "visual": "description", "cont": true}}
    ]
  }},
  ...
]"""

    response = client.models.generate_content(
        model=model_id,
        contents=batch_input_json,
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
        batch_results = json.loads(raw_resp)
    except json.JSONDecodeError:
        print("[ERROR] Gemini returned invalid JSON for batch surgery.")
        print(response.text[:500])
        return

    # Index results by scene_id for fast lookup
    results_by_id = {r['scene_id']: r['cuts'] for r in batch_results if 'scene_id' in r and 'cuts' in r}
    print(f"[BATCH] Gemini returned results for {len(results_by_id)} scene(s).")

    # -------------------------------------------------------
    # PASS 3: Apply all surgery results (pure Python, no API)
    # -------------------------------------------------------
    new_prompts = []
    surgery_performed = False

    for idx, p in enumerate(old_prompts):
        duration = float(p['timing']['duration'])

        # Check if this scene was sent for surgery
        matching_ls = next((ls for ls in long_scenes if ls['scene_idx'] == idx), None)

        if matching_ls is None or duration <= LONG_SCENE_THRESHOLD:
            new_prompts.append(p)
            continue

        cuts = results_by_id.get(idx)
        if not cuts:
            print(f"[ERROR] No Gemini result for scene {idx+1}. Keeping original.")
            new_prompts.append(p)
            continue

        seg_words    = matching_ls['seg_words']    # [(abs_i, word_dict), ...]
        abs_offset   = matching_ls['abs_offset']
        seg_end      = matching_ls['seg_end']
        n_seg_words  = len(seg_words)
        surgery_performed = True

        # Validate cuts and look up absolute timestamps
        compiled_sub = []
        last_wi = -1
        for cut in cuts:
            wi  = cut.get('wi')
            vis = cut.get('visual', '')
            cont = bool(cut.get('cont', False))

            if not isinstance(wi, int) or wi < 0 or wi >= n_seg_words:
                print(f"[SKIP] Scene {idx+1}: sub-scene wi={wi!r} out of range (0–{n_seg_words-1}).")
                continue
            if wi <= last_wi:
                print(f"[SKIP] Scene {idx+1}: wi={wi} not ascending (prev={last_wi}).")
                continue

            abs_i    = seg_words[wi][0]
            abs_word = words_data[abs_i]
            compiled_sub.append({
                "visual": vis,
                "cont":   cont,
                "start":  abs_word['start'],
            })
            last_wi = wi

        if not compiled_sub:
            print(f"[ERROR] Scene {idx+1}: all sub-scenes invalid. Keeping original.")
            new_prompts.append(p)
            continue

        # PREEMPT FIX for sub-scenes (not the very first sub-scene if it was scene 0)
        is_very_first = (idx == 0)
        if is_very_first:
            compiled_sub[0]['start'] = 0.0

        for j in range(0 if is_very_first else 0, len(compiled_sub)):
            if not (is_very_first and j == 0):
                compiled_sub[j]['start'] = max(0.0, compiled_sub[j]['start'] - PREEMPT_OFFSET)

        # Compute end/duration
        for j, sub in enumerate(compiled_sub):
            if j < len(compiled_sub) - 1:
                end = compiled_sub[j + 1]['start']
            else:
                end = seg_end
            sub['end']      = end
            sub['duration'] = round(end - sub['start'], 3)

        # Build prompt objects for each sub-scene
        for sub in compiled_sub:
            visual_desc   = sub['visual'].replace("[MC]", MAIN_CHARACTER_DESC)
            styled_visual = BASE_TEMPLATE.format(visual=visual_desc)
            full_prompt   = (CONTINUITY_PREFIX + styled_visual) if sub['cont'] else styled_visual

            new_prompts.append({
                "visual_kind":     "illustration",
                "generation_mode": "create",
                "visual_recipe":   "doodle-prehistoric-male",
                "timing": {
                    "start":    sub['start'],
                    "end":      sub['end'],
                    "duration": sub['duration'],
                },
                "output": p.get('output', {"file": "000.png", "format": "png"}),
                "refs":   [],
                "prompt": full_prompt,
            })

        print(f"[OK] Scene {idx+1}: split into {len(compiled_sub)} sub-scenes.")

    if not surgery_performed:
        print("[INFO] No surgery was applied.")
        return

    # Re-number all prompts sequentially
    for i, p in enumerate(new_prompts):
        p['order']   = i + 1
        p['shot_id'] = i + 1
        p['output']  = {"file": f"{(i + 1):03d}.png", "format": "png"}

    prompts_data['prompts']    = new_prompts
    prompts_data['shot_count'] = len(new_prompts)

    with open(prompts_json_path, 'w', encoding='utf-8') as f:
        json.dump(prompts_data, f, indent=2, ensure_ascii=False)

    txt_path = os.path.join(project_dir, f"prompts_chunk_{chunk_index}.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        for p in new_prompts:
            f.write(f"[{p['timing']['start']}-{p['timing']['end']}] {p['prompt']}\n")

    print(f"\n[SUCCESS] Micro-Surgery complete. Expanded from {len(old_prompts)} → {len(new_prompts)} scenes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--chunk',   type=int, required=True)
    parser.add_argument('--project', type=str, required=True)
    args = parser.parse_args()
    reprocess_surgery(args.chunk, args.project)
