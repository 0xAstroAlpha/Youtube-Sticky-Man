import os
import json
import asyncio
import glob
import uuid
import shutil
import zipfile
from io import BytesIO
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

app.mount("/static", StaticFiles(directory="web/static"), name="static")

@app.get("/")
async def root():
    return FileResponse("web/static/index.html")

@app.post("/api/process")
async def process_script(file: UploadFile = File(...), voice_id: str = Form("QzTKubutNn9TjrB7Xb2Q"), model_id: str = Form("eleven_multilingual_v2")):
    # Generate unique project ID for multi-tenant isolation
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    project_dir = os.path.join("projects", project_id)
    os.makedirs(project_dir, exist_ok=True)
    
    # Clean filename and save
    file_path = os.path.join(project_dir, file.filename)
    
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
        
    # Store metadata
    meta = {
        "project_name": os.path.splitext(file.filename)[0],
        "project_id": project_id,
        "voice_id": voice_id,
        "model_id": model_id
    }
    with open(os.path.join(project_dir, "meta.json"), "w") as f:
        json.dump(meta, f)
        
    return {"status": "success", "project_id": project_id, "project_name": meta["project_name"], "file_path": file_path, "voice_id": voice_id, "model_id": model_id}

@app.get("/api/stream")
async def stream_logs(request: Request, project_id: str, file_path: str, voice_id: str, model_id: str):
    project_dir = os.path.join("projects", project_id)
    async def event_generator():
        yield f"data: [INFO] Starting pipeline for project: {project_id}\n\n"
        
        yield f"data: [INFO] >>> STEP 1: Running intelligent text chunker...\n\n"
        chunker_cmd = ["python", ".agents/skills/long-video-workflow/scripts/text_chunker.py", "--input", file_path, "--out-dir", project_dir, "--max-chars", "4500"]
        process = await asyncio.create_subprocess_exec(*chunker_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        
        while True:
            line = await process.stdout.readline()
            if not line: break
            yield f"data: {line.decode('utf-8').strip()}\n\n"
        await process.wait()
        
        chunks = [f for f in os.listdir(project_dir) if f.startswith("chunk_") and f.endswith(".txt")]
        chunks.sort(key=lambda x: int(x.split('_')[1].split('.')[0]))
        
        yield f"data: [INFO] >>> Step 1 Complete. Found {len(chunks)} chunks.\n\n"
        
        for chunk in chunks:
            chunk_index = chunk.split('_')[1].split('.')[0]
            chunk_path = os.path.join(project_dir, chunk)
            audio_path = os.path.join(project_dir, f"audio_chunk_{chunk_index}.mp3")
            json_path = os.path.join(project_dir, f"transcript_chunk_{chunk_index}.json")
            
            yield f"data: [INFO] >>> STEP 2: Running TTS for chunk {chunk_index}...\n\n"
            if os.path.exists(audio_path) and os.path.exists(json_path):
                yield f"data: [INFO] >>> Audio already exists for chunk {chunk_index}. Skipping ElevenLabs TTS to save credits.\n\n"
            else:
                tts_cmd = ["python", ".agents/skills/long-video-workflow/scripts/elevenlabs_tts_with_timestamps.py", "--input-file", chunk_path, "--voice-id", voice_id, "--model-id", model_id, "--out-audio", audio_path, "--out-json", json_path]
                process = await asyncio.create_subprocess_exec(*tts_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                while True:
                    line = await process.stdout.readline()
                    if not line: break
                    yield f"data: {line.decode('utf-8').strip()}\n\n"
                await process.wait()
            
            yield f"data: [INFO] >>> STEP 3: Generating Semantic Prompts for chunk {chunk_index}...\n\n"
            gemini_cmd = ["python", ".agents/skills/long-video-workflow/scripts/generate_semantic_prompts.py", "--chunk", chunk_index, "--transcript", json_path]
            process = await asyncio.create_subprocess_exec(*gemini_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            while True:
                line = await process.stdout.readline()
                if not line: break
                yield f"data: {line.decode('utf-8').strip()}\n\n"
            await process.wait()
            
        yield f"data: [INFO] >>> PIPELINE COMPLETE! All files and folders are ready in the '{project_id}' directory.\n\n"
        yield "data: [DONE]\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream")


# Updated to accept a list of project IDs from the client to enforce isolation
@app.post("/api/projects/list")
async def list_projects(request: Request):
    data = await request.json()
    client_projects = data.get("projects", [])
    
    projects = []
    if not os.path.exists("projects"):
        os.makedirs("projects", exist_ok=True)
        
    for p_id in client_projects:
        proj_dir = os.path.join("projects", p_id)
        if os.path.isdir(proj_dir):
            # Check if processing has started (prompts exist) or at least meta exists
            if os.path.exists(os.path.join(proj_dir, "meta.json")):
                with open(os.path.join(proj_dir, "meta.json"), "r") as f:
                    meta = json.load(f)
                projects.append({
                    "id": p_id,
                    "name": meta.get("project_name", p_id)
                })
    return {"status": "success", "projects": projects}


@app.get("/api/projects/{proj_id}")
async def get_project_details(proj_id: str):
    proj_dir = os.path.join("projects", proj_id)
    if not os.path.exists(proj_dir):
        return {"status": "error", "message": "Project not found"}
        
    jsons = glob.glob(os.path.join(proj_dir, "image_prompts_chunk_*.json"))
    chunks_data = []
    total_ready = True
    
    for jf in sorted(jsons):
        basename = os.path.basename(jf)
        chunk_idx = basename.replace("image_prompts_chunk_", "").replace(".json", "")
        
        with open(jf, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        prompts = data.get("prompts", [])
        prompts_count = len(prompts)
        
        max_duration = 0.0
        for p in prompts:
            dur = float(p['timing']['end']) - float(p['timing']['start'])
            if dur > max_duration:
                max_duration = dur
        
        audit_pass = max_duration <= 8.0
        
        images_dir = os.path.join(proj_dir, f"images_chunk_{chunk_idx}")
        images_count = 0
        if os.path.exists(images_dir):
            image_files = [img for img in os.listdir(images_dir) if img.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
            images_count = len(image_files)
            
        ready = images_count >= prompts_count
        if not ready:
            total_ready = False
            
        chunks_data.append({
            "chunk": chunk_idx,
            "prompts": prompts_count,
            "images": images_count,
            "ready": ready,
            "audit_pass": audit_pass,
            "max_duration": round(max_duration, 2)
        })
        
    # Check if final video exists
    video_ready = False
    video_path = os.path.join(proj_dir, "output", "final_video.mp4")
    if os.path.exists(video_path):
        video_ready = True
        
    return {"status": "success", "chunks": chunks_data, "total_ready": total_ready, "video_ready": video_ready}


@app.get("/api/projects/{proj_id}/stitch")
async def stitch_project_all(request: Request, proj_id: str):
    proj_dir = os.path.join("projects", proj_id)
    async def stitch_generator():
        yield f"data: [INFO] Starting Full FFmpeg Stitching Engine for {proj_id}...\n\n"
        stitch_cmd = ["python", ".agents/skills/long-video-workflow/scripts/stitch_video.py", "--project", proj_dir]
        process = await asyncio.create_subprocess_exec(*stitch_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        while True:
            line = await process.stdout.readline()
            if not line: break
            yield f"data: {line.decode('utf-8').strip()}\n\n"
        await process.wait()
        yield "data: [DONE]\n\n"
    return StreamingResponse(stitch_generator(), media_type="text/event-stream")


@app.get("/api/projects/{proj_id}/stitch/{chunk_id}")
async def stitch_project_chunk(request: Request, proj_id: str, chunk_id: str):
    proj_dir = os.path.join("projects", proj_id)
    async def stitch_generator():
        yield f"data: [INFO] Starting Granular Stitching Engine for {proj_id} - Chunk {chunk_id}...\n\n"
        stitch_cmd = ["python", ".agents/skills/long-video-workflow/scripts/stitch_video.py", "--project", proj_dir, "--chunk", chunk_id]
        process = await asyncio.create_subprocess_exec(*stitch_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        while True:
            line = await process.stdout.readline()
            if not line: break
            yield f"data: {line.decode('utf-8').strip()}\n\n"
        await process.wait()
        yield "data: [DONE]\n\n"
    return StreamingResponse(stitch_generator(), media_type="text/event-stream")


@app.get("/api/projects/{proj_id}/re-prompt/{chunk_id}")
async def reprompt_chunk(request: Request, proj_id: str, chunk_id: str):
    proj_dir = os.path.join("projects", proj_id)
    async def reprompt_generator():
        yield f"data: [INFO] RE-PROMPTING Chunk {chunk_id} in {proj_id} (Skipping TTS)...\n\n"
        json_path = os.path.join(proj_dir, f"transcript_chunk_{chunk_id}.json")
        gemini_cmd = ["python", ".agents/skills/long-video-workflow/scripts/generate_semantic_prompts.py", "--chunk", chunk_id, "--transcript", json_path]
        
        process = await asyncio.create_subprocess_exec(*gemini_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        while True:
            line = await process.stdout.readline()
            if not line: break
            yield f"data: {line.decode('utf-8').strip()}\n\n"
        await process.wait()
        yield "data: [DONE]\n\n"
    return StreamingResponse(reprompt_generator(), media_type="text/event-stream")

@app.get("/api/projects/{proj_id}/surgery/{chunk_id}")
async def surgery_chunk(request: Request, proj_id: str, chunk_id: str):
    proj_dir = os.path.join("projects", proj_id)
    async def surgery_generator():
        yield f"data: [INFO] Performing MICRO-SURGERY on Chunk {chunk_id} in {proj_id}...\n\n"
        surgery_cmd = ["python", ".agents/skills/long-video-workflow/scripts/reprocess_long_scenes.py", "--chunk", chunk_id, "--project", proj_dir]
        
        process = await asyncio.create_subprocess_exec(*surgery_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        while True:
            line = await process.stdout.readline()
            if not line: break
            yield f"data: {line.decode('utf-8').strip()}\n\n"
        await process.wait()
        yield "data: [DONE]\n\n"
    return StreamingResponse(surgery_generator(), media_type="text/event-stream")

# --- NEW: Download & Upload APIs ---

def create_zip_from_pattern(pattern: str, zip_filename: str):
    files = glob.glob(pattern)
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, os.path.basename(f))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={zip_filename}"})

@app.get("/api/projects/{proj_id}/download/audio")
async def download_audio(proj_id: str):
    proj_dir = os.path.join("projects", proj_id)
    if not os.path.exists(proj_dir): return JSONResponse(status_code=404, content={"message": "Project not found"})
    return create_zip_from_pattern(os.path.join(proj_dir, "*.mp3"), f"{proj_id}_audio.zip")

@app.get("/api/projects/{proj_id}/download/prompts")
async def download_prompts(proj_id: str):
    proj_dir = os.path.join("projects", proj_id)
    if not os.path.exists(proj_dir): return JSONResponse(status_code=404, content={"message": "Project not found"})
    files = glob.glob(os.path.join(proj_dir, "prompts_chunk_*.txt")) + glob.glob(os.path.join(proj_dir, "image_prompts_chunk_*.json"))
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files: zf.write(f, os.path.basename(f))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={proj_id}_prompts.zip"})

@app.post("/api/projects/{proj_id}/upload/{chunk_id}")
async def upload_images(proj_id: str, chunk_id: str, files: list[UploadFile] = File(...)):
    proj_dir = os.path.join("projects", proj_id)
    if not os.path.exists(proj_dir): return JSONResponse(status_code=404, content={"message": "Project not found"})
    
    images_dir = os.path.join(proj_dir, f"images_chunk_{chunk_id}")
    os.makedirs(images_dir, exist_ok=True)
    
    saved = 0
    for file in files:
        if file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            with open(os.path.join(images_dir, file.filename), "wb") as f:
                content = await file.read()
                f.write(content)
            saved += 1
            
    return {"status": "success", "message": f"Saved {saved} images"}

@app.get("/api/projects/{proj_id}/download/video")
async def download_video(proj_id: str):
    video_path = os.path.join("projects", proj_id, "output", "final_video.mp4")
    if not os.path.exists(video_path): return JSONResponse(status_code=404, content={"message": "Video not found"})
    return FileResponse(video_path, filename=f"{proj_id}_final_video.mp4")
