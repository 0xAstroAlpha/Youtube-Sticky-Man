import os
import json
import asyncio
import glob
import shutil
import zipfile
from io import BytesIO
from typing import List
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import base64
import secrets
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

@app.middleware("http")
async def basic_auth(request: Request, call_next):
    # Only protect API endpoints
    if not request.url.path.startswith("/api"):
        return await call_next(request)

    correct_password = os.getenv("APP_PASSWORD", "sticky123")
    
    # Check header
    auth_header = request.headers.get("X-App-Password")
    if auth_header and secrets.compare_digest(auth_header, correct_password):
        return await call_next(request)
        
    # Check query param (for EventSource, Download links, Video etc)
    pwd_query = request.query_params.get("pwd")
    if pwd_query and secrets.compare_digest(pwd_query, correct_password):
        return await call_next(request)
            
    from fastapi import Response
    return Response(content="Unauthorized", status_code=401)

app.mount("/static", StaticFiles(directory="web/static"), name="static")

@app.get("/")
async def root():
    return FileResponse("web/static/index.html")

@app.post("/api/process")
async def process_script(file: UploadFile = File(...), voice_id: str = Form("QzTKubutNn9TjrB7Xb2Q"), model_id: str = Form("eleven_multilingual_v2")):
    project_name = os.path.splitext(file.filename)[0]
    os.makedirs(project_name, exist_ok=True)
    
    file_path = os.path.join(project_name, file.filename)
    
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
        
    return {"status": "success", "project_name": project_name, "file_path": file_path, "voice_id": voice_id, "model_id": model_id}

@app.get("/api/stream")
async def stream_logs(request: Request, project_name: str, file_path: str, voice_id: str, model_id: str):
    async def event_generator():
        yield f"data: [INFO] Starting pipeline for project: {project_name}\n\n"
        
        yield f"data: [INFO] >>> STEP 1: Chunking the script into ~5000-character segments...\n\n"
        chunker_cmd = ["python", ".agents/skills/long-video-workflow/scripts/text_chunker.py", "--input", file_path, "--out-dir", project_name, "--max-chars", "5000"]
        process = await asyncio.create_subprocess_exec(*chunker_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        
        while True:
            line = await process.stdout.readline()
            if not line: break
            yield f"data: {line.decode('utf-8').strip()}\n\n"
        await process.wait()
        
        chunks = [f for f in os.listdir(project_name) if f.startswith("chunk_") and f.endswith(".txt")]
        chunks.sort(key=lambda x: int(x.split('_')[1].split('.')[0]))
        
        yield f"data: [INFO] >>> Step 1 Complete. Found {len(chunks)} chunks.\n\n"
        
        for chunk in chunks:
            chunk_index = chunk.split('_')[1].split('.')[0]
            chunk_path = os.path.join(project_name, chunk)
            audio_path = os.path.join(project_name, f"audio_chunk_{chunk_index}.mp3")
            json_path = os.path.join(project_name, f"transcript_chunk_{chunk_index}.json")
            
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
            
        yield f"data: [INFO] >>> PIPELINE COMPLETE! All files and folders are ready in the '{project_name}' directory.\n\n"
        yield "data: [DONE]\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@app.get("/api/projects")
async def list_projects():
    projects = []
    for entry in os.scandir("."):
        if entry.is_dir() and not entry.name.startswith(('.', '__')) and entry.name not in ["web", "archive", "output", "projects"]:
            jsons = glob.glob(os.path.join(entry.name, "image_prompts_chunk_*.json"))
            if jsons:
                projects.append(entry.name)
    return {"status": "success", "projects": projects}

@app.get("/api/projects/{name}")
async def get_project_details(name: str):
    if not os.path.exists(name):
        return {"status": "error", "message": "Project not found"}
        
    txt_files = glob.glob(os.path.join(name, "chunk_*.txt"))
    chunks_data = []
    total_ready = True
    
    # Sort numerically based on chunk index
    def get_chunk_idx(filepath):
        basename = os.path.basename(filepath)
        idx_str = basename.replace("chunk_", "").replace(".txt", "")
        return int(idx_str) if idx_str.isdigit() else 0
        
    for txt in sorted(txt_files, key=get_chunk_idx):
        chunk_idx = str(get_chunk_idx(txt))
        jf = os.path.join(name, f"image_prompts_chunk_{chunk_idx}.json")
        
        if not os.path.exists(jf):
            chunks_data.append({
                "chunk": chunk_idx,
                "prompts": 0,
                "images": 0,
                "ready": False,
                "audit_pass": False,
                "max_duration": 0,
                "error": True
            })
            total_ready = False
            continue
            
        with open(jf, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                # Handle corrupted json
                chunks_data.append({
                    "chunk": chunk_idx,
                    "prompts": 0,
                    "images": 0,
                    "ready": False,
                    "audit_pass": False,
                    "max_duration": 0,
                    "error": True
                })
                total_ready = False
                continue
                
        prompts = data.get("prompts", [])
        num_prompts = len(prompts)
        images_dir = os.path.join(name, f"images_chunk_{chunk_idx}")
        images_count = 0
        if os.path.exists(images_dir):
            images_count = len([f for f in os.listdir(images_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))])
            
        ready = (images_count >= num_prompts) and (num_prompts > 0)
        if not ready:
            total_ready = False
            
        # Pacing Audit
        max_duration = 0.0
        for p in prompts:
            try:
                dur = float(p['timing']['end']) - float(p['timing']['start'])
            except (KeyError, TypeError, ValueError):
                dur = 0.0
            if dur > max_duration:
                max_duration = dur
                
        audit_pass = max_duration <= 8.0
            
        chunks_data.append({
            "chunk": chunk_idx,
            "prompts": num_prompts,
            "images": images_count,
            "ready": ready,
            "audit_pass": audit_pass,
            "max_duration": round(max_duration, 2),
            "error": False
        })
        
    # Check if final video exists
    video_ready = False
    video_path = os.path.join(name, "output", "final_video.mp4")
    if os.path.exists(video_path):
        video_ready = True
        
    return {"status": "success", "chunks": chunks_data, "total_ready": total_ready, "video_ready": video_ready}


@app.get("/api/projects/{name}/stitch")
async def stitch_project_all(request: Request, name: str):
    async def stitch_generator():
        yield f"data: [INFO] Starting Full FFmpeg Stitching Engine for {name}...\n\n"
        stitch_cmd = ["python", ".agents/skills/long-video-workflow/scripts/stitch_video.py", "--project", name]
        process = await asyncio.create_subprocess_exec(*stitch_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        while True:
            line = await process.stdout.readline()
            if not line: break
            yield f"data: {line.decode('utf-8').strip()}\n\n"
        await process.wait()
        yield "data: [DONE]\n\n"
    return StreamingResponse(stitch_generator(), media_type="text/event-stream")


@app.get("/api/projects/{name}/stitch/{chunk_id}")
async def stitch_project_chunk(request: Request, name: str, chunk_id: str):
    async def stitch_generator():
        yield f"data: [INFO] Starting Granular Stitching Engine for {name} - Chunk {chunk_id}...\n\n"
        stitch_cmd = ["python", ".agents/skills/long-video-workflow/scripts/stitch_video.py", "--project", name, "--chunk", chunk_id]
        process = await asyncio.create_subprocess_exec(*stitch_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        while True:
            line = await process.stdout.readline()
            if not line: break
            yield f"data: {line.decode('utf-8').strip()}\n\n"
        await process.wait()
        yield "data: [DONE]\n\n"
    return StreamingResponse(stitch_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@app.get("/api/projects/{name}/re-prompt/{chunk_id}")
async def reprompt_chunk(request: Request, name: str, chunk_id: str):
    async def reprompt_generator():
        yield f"data: [INFO] RE-PROMPTING Chunk {chunk_id} in {name} (Skipping TTS)...\n\n"
        json_path = os.path.join(name, f"transcript_chunk_{chunk_id}.json")
        gemini_cmd = ["python", ".agents/skills/long-video-workflow/scripts/generate_semantic_prompts.py", "--chunk", chunk_id, "--transcript", json_path]
        
        process = await asyncio.create_subprocess_exec(*gemini_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        while True:
            line = await process.stdout.readline()
            if not line: break
            yield f"data: {line.decode('utf-8').strip()}\n\n"
        await process.wait()
        yield "data: [DONE]\n\n"
    return StreamingResponse(reprompt_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

@app.get("/api/projects/{name}/surgery/{chunk_id}")
async def surgery_chunk(request: Request, name: str, chunk_id: str):
    async def surgery_generator():
        yield f"data: [INFO] Performing MICRO-SURGERY on Chunk {chunk_id} in {name}...\n\n"
        surgery_cmd = ["python", ".agents/skills/long-video-workflow/scripts/reprocess_long_scenes.py", "--chunk", chunk_id, "--project", name]
        
        process = await asyncio.create_subprocess_exec(*surgery_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        while True:
            line = await process.stdout.readline()
            if not line: break
            yield f"data: {line.decode('utf-8').strip()}\n\n"
        await process.wait()
        yield "data: [DONE]\n\n"
    return StreamingResponse(surgery_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

# --- NEW: Download & Upload APIs ---

def create_zip_from_pattern(pattern: str, zip_filename: str):
    files = glob.glob(pattern)
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, os.path.basename(f))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={zip_filename}"})

@app.get("/api/projects/{name}/download/audio")
async def download_audio(name: str):
    if not os.path.exists(name): return JSONResponse(status_code=404, content={"message": "Project not found"})
    return create_zip_from_pattern(os.path.join(name, "*.mp3"), f"{name}_audio.zip")

@app.get("/api/projects/{name}/download/prompts")
async def download_prompts(name: str):
    if not os.path.exists(name): return JSONResponse(status_code=404, content={"message": "Project not found"})
    files = glob.glob(os.path.join(name, "prompts_chunk_*.txt")) + glob.glob(os.path.join(name, "image_prompts_chunk_*.json"))
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files: zf.write(f, os.path.basename(f))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={name}_prompts.zip"})

@app.post("/api/projects/{name}/upload/{chunk_id}")
async def upload_images(name: str, chunk_id: str, files: List[UploadFile] = File(...)):
    if not os.path.exists(name): return JSONResponse(status_code=404, content={"message": "Project not found"})
    
    images_dir = os.path.join(name, f"images_chunk_{chunk_id}")
    os.makedirs(images_dir, exist_ok=True)
    
    saved = 0
    for file in files:
        if file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            with open(os.path.join(images_dir, file.filename), "wb") as f:
                content = await file.read()
                f.write(content)
            saved += 1
            
    return {"status": "success", "message": f"Saved {saved} images"}

@app.get("/api/projects/{name}/download/video")
async def download_video(name: str):
    video_path = os.path.join(name, "output", "final_video.mp4")
    if not os.path.exists(video_path): return JSONResponse(status_code=404, content={"message": "Video not found"})
    return FileResponse(video_path, filename=f"{name}_final_video.mp4")
