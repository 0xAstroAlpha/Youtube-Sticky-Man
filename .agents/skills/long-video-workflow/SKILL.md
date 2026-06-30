---
name: long-video-workflow
description: Handles long-form YouTube video generation by chunking scripts, generating audio/transcripts, planning dynamic word-level prompts locally, waiting for user image rendering, and stitching via FFmpeg.
---

# Long-Form Video Workflow

This skill defines the complete pipeline and strict rules for processing video scripts. 

## Part 1: The Core Pipeline

### Step 1: Chunking (Automated Intelligent Chunker)
- The Agent MUST NOT attempt to split the text manually.
- Run the included intelligent text chunker script. This script dynamically splits the text at double-newlines (paragraphs) or sentences to guarantee sentences are never broken, keeping each part under the character limit:
  `python .agents/skills/long-video-workflow/scripts/text_chunker.py --input path/to/script.txt --out-dir output/dir/ --max-chars 4500`
- The script automatically outputs `chunk_1.txt`, `chunk_2.txt`... regardless of how many parts it takes.

### Step 2: Audio & Transcript Generation
- Run the included TTS script located at `.agents/skills/long-video-workflow/scripts/elevenlabs_tts_with_timestamps.py` on each chunk.
- For each chunk, save both the audio and the exact word-level transcript (e.g., `audio_chunk_1.mp3`, `transcript_chunk_1.json`).

### Step 3: Local Prompt Generation (Automated Gemini Semantic Intelligence)
- **Prerequisite**: The User must provide their Gemini API key in `.agents/skills/long-video-workflow/scripts/.env` (see `.env.example`). Also install dependencies from `requirements.txt`.
- **CRITICAL RULE**: Do not use mechanical duration-based splitters. Do NOT attempt to map the semantic words manually.
- **Workflow**:
  - Run the included semantic prompt generation app for each chunk:
    `python .agents/skills/long-video-workflow/scripts/generate_semantic_prompts.py --chunk X --transcript path/to/transcript_chunk_X.json`
  - The script will automatically call Gemini 3.1 Flash with strict styling rules, map the visual scenes to the exact millisecond timestamps in the JSON, and output `prompts_chunk_X.txt` and `image_prompts_chunk_X.json` in the same directory.
- Proceed to the next chunk until all chunks are completed.

### Step 4: Video Stitching
- **Folder Structure**: The User must place generated images into specific sub-folders to prevent filename collision (since every chunk starts at `0001.png`):
  - `images_chunk_1/0001.png...`
  - `images_chunk_2/0001.png...`
- **Render Logic**: The Agent uses FFmpeg to stitch the images from `images_chunk_X` against `audio_chunk_X.mp3` to render an intermediate `video_chunk_X.mp4`.
- **Final Concat**: The Agent uses FFmpeg to concatenate all intermediate chunk videos into the `final_video.mp4`.
- **Alternative Stitching**: If the user explicitly requests a Kdenlive project for manual editing instead of raw FFmpeg stitching, use the included `.agents/skills/long-video-workflow/scripts/json_to_kdenlive_project.py` script.

---

## Part 2: Strict Workflow Rules

### Rule 1: Dynamic Pacing
- Choose visuals that map tightly to specific words or phrases (**1-4 seconds per shot**). Avoid long, static shots for entire sentences.
- Bad: One image holds for a full 10-second sentence.
- Good: The scene cuts 3 times across a 10-second sentence, visually emphasizing key phrases.

### Rule 2: Visual Recipe Lock
- **Base Formula**: `Hand-drawn 2D doodle cartoon animation, flat colors, bold black outlines, slightly imperfect sketchy marker lines, [SPECIFIC VISUALS], stark white background, no gradients, no shadows, no textures, no photorealism, no 3D, 16:9 aspect ratio, educational YouTube explainer doodle style.`
- **Character Lock**: `the recurring character is a primitive prehistoric male stick figure wearing animal skins, same face and body proportions across shots`

### Rule 3: One-Line Prompts
- Every prompt must be one physical line.
- No newlines inside any prompt in `prompts.txt`.

### Rule 4: Output Specs & Naming Conventions
- **prompts.txt**: Must look like `[0-1.74] Hand-drawn 2D doodle...`
- **image_prompts.json**: Top level must contain `"schema": "sticky-man.prompt-pack.v1"`, `"shot_count"`, `"total_duration"`, and `"prompts"`.
- **Image File Naming**: All generated image files must use EXACTLY four digits (e.g., `0001.png`, `0002.png`, `0012.png`). Forbidden formats: `shot_0001.png`, `image1.png`, `frame-1.png`.

### Rule 5: Red X & Continuity
- **Red X Rule**: Use a giant bold red X ONLY for rejected choices, forbidden objects, negated concepts, or wrong habits. Do not use as generic decoration.
- **Continuity Rule**: When the next shot belongs to the same scene, the next prompt must say: `Continuity instruction: use the scene_previous reference as the prior animation beat. Preserve character identity, camera distance, visual scale, white background, and line weight.`

### Rule 6: Hero Title Rule
- Do not overlay title text during video rendering.
- For hero title shots, the image prompt must request the image model to render the exact title INSIDE the image.
