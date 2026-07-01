import argparse
import json
import os
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

def generate_prompts(chunk_index, transcript_path):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env")
        return

    with open(transcript_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    raw_text = data['text']
    text_content = re.sub(r'\[.*?\]', '', raw_text).strip()
    words_data = data['words']

    client = genai.Client(api_key=api_key)
    
    sys_instruction = """You are an expert director for an educational YouTube doodle animation channel.
Your task is to break down a provided text into a chronological sequence of highly visual, impactful scenes (1-4 seconds each).
For each scene, identify the EXACT word in the text where the cut should happen (the "target_word") and describe the visual scene ("visual").

CRITICAL TIMING & PACING RULES:
1. You MUST process the ENTIRE provided text from the very first word to the very last word. Do not skip, summarize, or truncate any parts.
2. A text of this length MUST yield between 20 to 40 scenes. You must pick a new `target_word` roughly every 15 to 30 words.
3. Target Word: Must be exactly as it appears in the text, sequentially.
4. Visual pacing: Steady and engaging. Each scene should last between 2 to 5 seconds. Avoid making scenes less than 2 seconds or longer than 5 seconds.
5. Character Lock: Use the exact literal string "[MC]" anytime you refer to the main character. Do NOT type out the full description. Example: "[MC] holding a spear".
6. Red X Rule: Use a giant bold red X ONLY for rejected choices, forbidden objects, or wrong habits. Do not use as generic decoration.
7. Do NOT include the base styling recipe (e.g. "Hand-drawn 2D doodle cartoon...") in your "visual" output, just describe the action/scene. We will wrap it later.

OUTPUT FORMAT:
Return a strictly valid JSON array of objects, where each object has:
- "target_word": (string)
- "visual": (string)
"""

    print("Calling Gemini Pro API for high-quality scenes...")
    response = client.models.generate_content(
        model='gemini-3.1-pro-preview',
        contents=text_content,
        config=types.GenerateContentConfig(
            system_instruction=sys_instruction,
            response_mime_type="application/json",
            max_output_tokens=32768,
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
            ]
        )
    )

    try:
        raw_text = response.text.strip()
        if raw_text.endswith("]\n]") or raw_text.endswith("]]"):
            # Strip the very last bracket if Gemini accidentally duplicated it
            raw_text = raw_text.rsplit(']', 1)[0].strip()
            if not raw_text.endswith(']'):
                raw_text += ']'
        semantic_map = json.loads(raw_text)
    except json.JSONDecodeError:
        print("Error: Failed to parse Gemini response as JSON.")
        print(response.text)
        return

    print(f"Gemini returned {len(semantic_map)} scenes. Compiling timestamps...")

    compiled_shots = []
    search_start_idx = 0

    for shot in semantic_map:
        target_word = shot.get('target_word', '')
        
        # Find the word in words_data starting from search_start_idx, but only look ahead 100 words
        search_limit = min(search_start_idx + 100, len(words_data))
        for i in range(search_start_idx, search_limit):
            # Case insensitive, removing punctuation for matching
            w_clean = re.sub(r'[^\w\s]', '', words_data[i]['word'].lower())
            t_clean = re.sub(r'[^\w\s]', '', target_word.lower())
            
            if t_clean in w_clean or w_clean in t_clean:
                compiled_shots.append({
                    "target_word": target_word,
                    "visual": shot.get('visual', ''),
                    "start": words_data[i]['start'],
                    "end": words_data[i]['end']
                })
                search_start_idx = i + 1
                break

    if not compiled_shots:
        print("Error: Could not match any target words to the transcript.")
        return

    # THE ANCHOR FIX: Force the first image to start exactly when the audio starts (0.0s).
    compiled_shots[0]['start'] = 0.0
    
    # THE PREEMPT FIX (Video Editor Technique):
    # Cut the visual 100ms (0.1s) BEFORE the target word is spoken. 
    # This compensates for human visual/auditory processing lag, making cuts feel perfectly in-sync.
    PREEMPT_OFFSET = 0.1
    for i in range(1, len(compiled_shots)):
        compiled_shots[i]['start'] = max(0.0, compiled_shots[i]['start'] - PREEMPT_OFFSET)

    for i in range(len(compiled_shots)):
        if i < len(compiled_shots) - 1:
            duration = round(compiled_shots[i+1]['start'] - compiled_shots[i]['start'], 3)
            end = compiled_shots[i+1]['start']
        else:
            end = words_data[-1]['end']
            duration = round(end - compiled_shots[i]['start'], 3)
            
        compiled_shots[i]['end'] = end
        compiled_shots[i]['duration'] = duration

    base_template = "Hand-drawn 2D doodle cartoon animation, flat colors, bold black outlines, slightly imperfect sketchy marker lines, {visual}, stark white background, no gradients, no shadows, no textures, no photorealism, no 3D, 16:9 aspect ratio, educational YouTube explainer doodle style."
    main_character_desc = "a primitive prehistoric male stick figure wearing animal skins"

    prompts = []
    for i, shot in enumerate(compiled_shots):
        visual_desc = shot['visual'].replace("[MC]", main_character_desc)
        full_prompt = base_template.format(visual=visual_desc)
        
        prompts.append({
          "order": i + 1,
          "shot_id": i + 1,
          "visual_kind": "illustration",
          "generation_mode": "create",
          "visual_recipe": "doodle-prehistoric-male",
          "timing": {
            "start": shot['start'],
            "end": shot['end'],
            "duration": shot['duration']
          },
          "output": {
            "file": f"{(i+1):03d}.png",
            "format": "png"
          },
          "refs": [],
          "prompt": full_prompt
        })

    # The script should output to the same directory as the transcript
    output_dir = os.path.dirname(transcript_path)
    if not output_dir:
        output_dir = "."
        
    txt_path = os.path.join(output_dir, f"prompts_chunk_{chunk_index}.txt")
    json_path = os.path.join(output_dir, f"image_prompts_chunk_{chunk_index}.json")
    images_dir = os.path.join(output_dir, f"images_chunk_{chunk_index}")

    if not os.path.exists(images_dir):
        os.makedirs(images_dir)
        print(f"Created image storage directory: {images_dir}")

    with open(txt_path, 'w', encoding='utf-8') as f:
        for i, p in enumerate(prompts):
            f.write(f"[{p['timing']['start']}-{p['timing']['end']}] {p['prompt']}\n")

    out_data = {
      "schema": "sticky-man.prompt-pack.v1",
      "chunk_index": chunk_index,
      "shot_count": len(prompts),
      "total_duration": prompts[-1]['timing']['end'] if prompts else 0,
      "instructions": {
        "order": "Create images in ascending order.",
        "output": "Return files using each item.output.path or file.",
        "refs": "Use refs[] when the image tool supports reference images."
      },
      "prompts": prompts
    }

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(out_data, f, indent=2)

    print(f"Compilation Complete! Saved to {output_dir} with {len(prompts)} matched scenes.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--chunk', type=int, required=True, help='Chunk index to process')
    parser.add_argument('--transcript', type=str, required=True, help='Path to transcript JSON file')
    args = parser.parse_args()
    
    generate_prompts(args.chunk, args.transcript)
