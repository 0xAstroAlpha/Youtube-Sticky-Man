import os
import sys
import json
import subprocess
import argparse
import glob

def stitch_project(project_dir, specific_chunk=None):
    print(f"[INFO] Initializing FFmpeg Stitching Engine for project: {project_dir}")
    
    json_files = glob.glob(os.path.join(project_dir, "image_prompts_chunk_*.json"))
    if not json_files:
        print("[ERROR] No image_prompts_chunk_*.json found.")
        return
        
    chunks = []
    for jf in json_files:
        basename = os.path.basename(jf)
        chunk_idx = int(basename.replace("image_prompts_chunk_", "").replace(".json", ""))
        chunks.append(chunk_idx)
        
    chunks.sort()
    
    if specific_chunk is not None:
        if specific_chunk not in chunks:
            print(f"[ERROR] Chunk {specific_chunk} not found in project.")
            return
        chunks = [specific_chunk]
        print(f"[INFO] Granular mode: Only processing Chunk {specific_chunk}")
    
    final_videos = []
    
    for c in chunks:
        print(f"[INFO] Processing Chunk {c}...")
        json_path = os.path.join(project_dir, f"image_prompts_chunk_{c}.json")
        audio_path = os.path.join(project_dir, f"audio_chunk_{c}.mp3")
        images_dir = os.path.join(project_dir, f"images_chunk_{c}")
        concat_txt = os.path.join(project_dir, f"concat_chunk_{c}.txt")
        out_mp4 = os.path.join(project_dir, f"video_chunk_{c}.mp4")
        
        if not os.path.exists(audio_path):
            print(f"[ERROR] Missing {audio_path}")
            return
            
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        prompts = data.get("prompts", [])
        
        image_files = sorted(glob.glob(os.path.join(images_dir, "*.*")))
        image_files = [img for img in image_files if img.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
        
        actual_images = []
        json_updated = False
        
        for i, p in enumerate(prompts):
            prefix = f"{(i+1):03d}"
            # Support both new 001 and legacy 0001
            legacy_prefix = f"{(i+1):04d}"
            
            matched = [img for img in image_files if os.path.basename(img).startswith(prefix) or os.path.basename(img).startswith(legacy_prefix)]
            
            if not matched:
                print(f"[ERROR] Chunk {c}: Missing image starting with {prefix} (or {legacy_prefix}) for shot {i+1}. Aborting.")
                return
            
            chosen_img = matched[0]
            actual_images.append(chosen_img)
            
            # Update the JSON so Kdenlive reads the correct file name with suffix
            actual_filename = os.path.basename(chosen_img)
            if 'output' in p and p['output'].get('file') != actual_filename:
                p['output']['file'] = actual_filename
                json_updated = True
                
        if json_updated:
            print(f"[INFO] Updating {json_path} to sync filenames with suffixes...")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            
        print(f"[INFO] Generating FFmpeg concat file for chunk {c}...")
        with open(concat_txt, 'w', encoding='utf-8') as f:
            for i, p in enumerate(prompts):
                start_time = float(p['timing']['start'])
                end_time = float(p['timing']['end'])
                duration = end_time - start_time
                if duration <= 0: duration = 0.5
                
                img_path = os.path.abspath(actual_images[i]).replace("\\", "/")
                f.write(f"file '{img_path}'\n")
                f.write(f"duration {duration}\n")
                
            last_img_path = os.path.abspath(actual_images[-1]).replace("\\", "/")
            f.write(f"file '{last_img_path}'\n")

        print(f"[INFO] Rendering MP4 for chunk {c}...")
        cmd = [
            "ffmpeg", "-y", 
            "-f", "concat", 
            "-safe", "0", 
            "-i", os.path.abspath(concat_txt), 
            "-i", os.path.abspath(audio_path),
            "-c:v", "libx264", 
            "-pix_fmt", "yuv420p", 
            "-r", "30", 
            "-c:a", "aac", 
            "-b:a", "192k",
            "-shortest", 
            os.path.abspath(out_mp4)
        ]
        
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            print(f"[ERROR] FFmpeg failed for chunk {c}.")
            print(result.stderr)
            return
            
        final_videos.append(out_mp4)
        print(f"[INFO] Chunk {c} MP4 rendered successfully.")

        print(f"[INFO] Exporting Kdenlive Project for chunk {c}...")
        kdenlive_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "json_to_kdenlive_project.py")
        kdenlive_out = os.path.join(project_dir, f"kdenlive_chunk_{c}")
        kdenlive_cmd = [
            "python", kdenlive_script,
            "--json", os.path.abspath(json_path),
            "--images-dir", os.path.abspath(images_dir),
            "--audio", os.path.abspath(audio_path),
            "--out-dir", os.path.abspath(kdenlive_out),
            "--project-name", f"{os.path.basename(project_dir)}_Chunk_{c}",
            "--allow-non-digits4"
        ]
        
        k_result = subprocess.run(kdenlive_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if k_result.returncode != 0:
            print(f"[WARNING] Kdenlive export failed for chunk {c}.")
        else:
            print(f"[INFO] Kdenlive Project saved to {kdenlive_out}/")

    if specific_chunk is None:
        print("[INFO] Stitching all chunks into Final Video...")
        final_concat_txt = os.path.join(project_dir, "concat_all.txt")
        final_mp4 = os.path.join(project_dir, "FINAL_VIDEO.mp4")
        
        with open(final_concat_txt, 'w', encoding='utf-8') as f:
            for vid in final_videos:
                vid_path = os.path.abspath(vid).replace("\\", "/")
                f.write(f"file '{vid_path}'\n")
                
        cmd_final = [
            "ffmpeg", "-y", 
            "-f", "concat", 
            "-safe", "0", 
            "-i", os.path.abspath(final_concat_txt),
            "-c", "copy",
            os.path.abspath(final_mp4)
        ]
        
        result = subprocess.run(cmd_final, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            print("[ERROR] FFmpeg failed to concatenate chunks.")
            print(result.stderr)
            return
            
        print(f"[SUCCESS] Video Stitching Complete! Output saved to: {final_mp4}")
    else:
        print(f"[SUCCESS] Granular Stitching Complete for chunk {specific_chunk}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=str, required=True, help='Path to project directory')
    parser.add_argument('--chunk', type=int, default=None, help='Specific chunk index to process')
    args = parser.parse_args()
    stitch_project(args.project, args.chunk)
