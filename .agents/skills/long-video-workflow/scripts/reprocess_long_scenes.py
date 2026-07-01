import argparse
import json
import os
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

def reprocess_surgery(chunk_index, project_dir):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env")
        return

    client = genai.Client(api_key=api_key)
    
    transcript_path = os.path.join(project_dir, f"transcript_chunk_{chunk_index}.json")
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
    new_prompts = []
    surgery_performed = False
    
    PREEMPT_OFFSET = 0.1
    
    sys_instruction = """You are an expert director performing micro-surgery on an educational YouTube doodle animation channel.
The user provided a segment of text that belongs to a single scene which is currently TOO LONG.
Your task is to break down this segment into 2 or 3 smaller, highly visual, impactful scenes (2-5 seconds each).
For each scene, identify the EXACT word in the text where the cut should happen (the "target_word") and describe the visual scene ("visual").

CRITICAL TIMING & PACING RULES:
1. You MUST process the ENTIRE provided text from the very first word to the very last word. Do not skip, summarize, or truncate any parts.
2. Target Word: Must be exactly as it appears in the text, sequentially.
3. Visual pacing: Each scene should last between 2 to 5 seconds.
4. Character Lock: Use the exact literal string "[MC]" anytime you refer to the main character.
5. Red X Rule: Use a giant bold red X ONLY for rejected choices, forbidden objects, or wrong habits.
6. Do NOT include the base styling recipe (e.g. "Hand-drawn 2D doodle cartoon...") in your "visual" output.
7. Enumeration/List Rule: For sentences that contain a list of items or concepts, you MUST split EACH item in the list into its own separate scene to increase visual dynamism.
8. Contextual Splitting: Always split scenes based on the sentence's logical context, choosing the most impactful keyword as the `target_word` so the visual hits exactly when the keyword is spoken.

OUTPUT FORMAT:
Return a strictly valid JSON array of objects, where each object has:
- "target_word": (string)
- "visual": (string)
"""

    for idx, p in enumerate(old_prompts):
        start = float(p['timing']['start'])
        end = float(p['timing']['end'])
        duration = float(p['timing']['duration'])
        
        if duration > 8.0:
            print(f"[SURGERY] Scene {idx+1} is {duration}s long. Operating...")
            surgery_performed = True
            
            # Undo PREEMPT for accurate searching
            real_start = start
            if idx > 0:
                real_start += PREEMPT_OFFSET
                
            # Extract words for this segment
            segment_words = [w for w in words_data if w['start'] >= real_start - 0.2 and w['end'] <= end + 0.2]
            segment_text = " ".join([w['word'] for w in segment_words])
            
            if not segment_text.strip():
                print(f"[ERROR] Could not extract text for Scene {idx+1}. Skipping.")
                new_prompts.append(p)
                continue
                
            print(f"Segment text: {segment_text}")
            
            response = client.models.generate_content(
                model='gemini-3.1-pro-preview',
                contents=segment_text,
                config=types.GenerateContentConfig(
                    system_instruction=sys_instruction,
                    response_mime_type="application/json",
                    max_output_tokens=32768,
                    safety_settings=[
                        types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                        types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE)
                    ]
                )
            )
            
            try:
                raw_text = response.text.strip()
                if raw_text.endswith("]\n]") or raw_text.endswith("]]"):
                    raw_text = raw_text.rsplit(']', 1)[0].strip()
                    if not raw_text.endswith(']'):
                        raw_text += ']'
                semantic_map = json.loads(raw_text)
            except json.JSONDecodeError:
                print(f"[ERROR] Gemini returned invalid JSON for Scene {idx+1}. Skipping.")
                new_prompts.append(p)
                continue
                
            print(f"Gemini returned {len(semantic_map)} sub-scenes.")
            
            compiled_shots = []
            search_start_idx = words_data.index(segment_words[0]) if segment_words else 0
            search_end_idx = words_data.index(segment_words[-1]) + 1 if segment_words else len(words_data)
            
            for shot in semantic_map:
                target_word = shot.get('target_word', '')
                for i in range(search_start_idx, search_end_idx):
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
                print("[ERROR] Could not match target words. Skipping.")
                new_prompts.append(p)
                continue
                
            if idx == 0:
                compiled_shots[0]['start'] = 0.0
                
            for i in range(len(compiled_shots)):
                if not (idx == 0 and i == 0):
                    compiled_shots[i]['start'] = max(0.0, compiled_shots[i]['start'] - PREEMPT_OFFSET)
                    
            for i in range(len(compiled_shots)):
                if i < len(compiled_shots) - 1:
                    c_dur = round(compiled_shots[i+1]['start'] - compiled_shots[i]['start'], 3)
                    c_end = compiled_shots[i+1]['start']
                else:
                    c_end = end
                    c_dur = round(c_end - compiled_shots[i]['start'], 3)
                compiled_shots[i]['end'] = c_end
                compiled_shots[i]['duration'] = c_dur
                
            base_template = "Hand-drawn 2D doodle cartoon animation, flat colors, bold black outlines, slightly imperfect sketchy marker lines, {visual}, stark white background, no gradients, no shadows, no textures, no photorealism, no 3D, 16:9 aspect ratio, educational YouTube explainer doodle style."
            main_character_desc = "a primitive prehistoric male stick figure wearing animal skins"
            
            for shot in compiled_shots:
                visual_desc = shot['visual'].replace("[MC]", main_character_desc)
                full_prompt = base_template.format(visual=visual_desc)
                
                new_prompts.append({
                    "visual_kind": "illustration",
                    "generation_mode": "create",
                    "visual_recipe": "doodle-prehistoric-male",
                    "timing": {
                        "start": shot['start'],
                        "end": shot['end'],
                        "duration": shot['duration']
                    },
                    "output": p.get('output', {}),
                    "refs": [],
                    "prompt": full_prompt
                })
        else:
            new_prompts.append(p)
            
    if not surgery_performed:
        print("[INFO] No scenes > 8.0s found. Everything is optimal.")
        return
        
    for i, p in enumerate(new_prompts):
        p['order'] = i + 1
        p['shot_id'] = i + 1
        p['output'] = {
            "file": f"{(i+1):03d}.png",
            "format": "png"
        }
        
    prompts_data['prompts'] = new_prompts
    prompts_data['shot_count'] = len(new_prompts)
    
    with open(prompts_json_path, 'w', encoding='utf-8') as f:
        json.dump(prompts_data, f, indent=2)
        
    txt_path = os.path.join(project_dir, f"prompts_chunk_{chunk_index}.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        for i, p in enumerate(new_prompts):
            f.write(f"[{p['timing']['start']}-{p['timing']['end']}] {p['prompt']}\n")
            
    print(f"[SUCCESS] Micro-Surgery complete. Expanded to {len(new_prompts)} scenes.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--chunk', type=int, required=True)
    parser.add_argument('--project', type=str, required=True)
    args = parser.parse_args()
    reprocess_surgery(args.chunk, args.project)
