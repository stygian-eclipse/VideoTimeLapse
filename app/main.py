from __future__ import annotations

import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.video_processor import (
    ProcessingError,
    check_ffmpeg_tools,
    choose_output_path,
    process_timelapse,
    safe_output_name,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / "app"
WORK_DIR = ROOT_DIR / "work"
UPLOADS_ROOT = WORK_DIR / "uploads"
TEMP_ROOT = WORK_DIR / "temp"
OUTPUTS_ROOT = WORK_DIR / "outputs"

for directory in (UPLOADS_ROOT, TEMP_ROOT, OUTPUTS_ROOT):
    directory.mkdir(parents=True, exist_ok=True)


app = FastAPI(title="VideoTimeLapse", version="1.0.0")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


jobs_lock = threading.Lock()
jobs: dict[str, dict[str, Any]] = {}


def set_job_status(job_id: str, **kwargs: Any) -> None:
    with jobs_lock:
        existing = jobs.get(job_id, {})
        existing.update(kwargs)
        jobs[job_id] = existing


def append_job_message(job_id: str, message: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        messages = job.setdefault("messages", [])
        timestamp = datetime.now().strftime("%H:%M:%S")
        messages.append(f"[{timestamp}] {message}")


def parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.lower() in {"1", "true", "yes", "on"}


def validate_inputs(
    files: list[UploadFile],
    target_duration: float,
    transition_duration: float,
    output_filename: str,
) -> None:
    if len(files) < 2:
        raise HTTPException(status_code=400, detail="Please upload at least 2 MP4 files.")
    if not 5 <= target_duration <= 300:
        raise HTTPException(status_code=400, detail="Target duration must be between 5 and 300 seconds.")
    if not 0 <= transition_duration <= 3:
        raise HTTPException(status_code=400, detail="Transition duration must be between 0 and 3 seconds.")
    if not output_filename.strip():
        raise HTTPException(status_code=400, detail="Output filename is required.")

    for file in files:
        original_name = file.filename or ""
        if not original_name.lower().endswith(".mp4"):
            raise HTTPException(status_code=400, detail=f"Only MP4 files are allowed: {original_name}")


def save_uploads_to_session(files: list[UploadFile]) -> tuple[str, Path]:
    session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
    session_upload_dir = UPLOADS_ROOT / session_id
    session_upload_dir.mkdir(parents=True, exist_ok=True)

    for idx, upload in enumerate(files, start=1):
        original_name = Path(upload.filename or f"clip_{idx}.mp4").name
        safe_name = safe_output_name(original_name)
        destination = session_upload_dir / safe_name
        counter = 1
        while destination.exists():
            destination = session_upload_dir / f"{Path(safe_name).stem}_{counter}.mp4"
            counter += 1
        with destination.open("wb") as target_file:
            shutil.copyfileobj(upload.file, target_file)
        upload.file.close()

    return session_id, session_upload_dir


def run_processing_job(
    job_id: str,
    upload_dir: Path,
    target_duration: float,
    transition_duration: float,
    output_filename: str,
    use_crossfade: bool,
) -> None:
    try:
        set_job_status(job_id, state="running")
        append_job_message(job_id, "Processing started.")
        input_files = sorted(upload_dir.glob("*.mp4"))
        if len(input_files) < 2:
            raise ProcessingError("Less than 2 uploaded MP4 files were found after upload.")

        output_path = choose_output_path(OUTPUTS_ROOT, output_filename)
        output_path = process_timelapse(
            input_files=input_files,
            output_path=output_path,
            target_duration=target_duration,
            transition_duration=transition_duration,
            use_crossfade=use_crossfade,
            status_callback=lambda m: append_job_message(job_id, m),
            temp_root=TEMP_ROOT,
        )
        set_job_status(
            job_id,
            state="completed",
            output_file=output_path.name,
            download_url=f"/download/{output_path.name}",
        )
        append_job_message(job_id, "Processing completed successfully.")
    except ProcessingError as exc:
        set_job_status(job_id, state="error", error=str(exc))
        append_job_message(job_id, f"Error: {exc}")
    except Exception as exc:  # noqa: BLE001
        set_job_status(job_id, state="error", error=f"Unexpected error: {exc}")
        append_job_message(job_id, f"Unexpected error: {exc}")


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    ffmpeg_ok = True
    ffmpeg_error = ""
    try:
        check_ffmpeg_tools()
    except ProcessingError as exc:
        ffmpeg_ok = False
        ffmpeg_error = str(exc)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"ffmpeg_ok": ffmpeg_ok, "ffmpeg_error": ffmpeg_error},
    )


@app.get("/health")
def health() -> JSONResponse:
    tools_available = True
    tools_error = ""
    try:
        check_ffmpeg_tools()
    except ProcessingError as exc:
        tools_available = False
        tools_error = str(exc)
    return JSONResponse(
        {
            "status": "ok",
            "ffmpeg_available": tools_available,
            "message": tools_error if tools_error else "ready",
        }
    )


@app.post("/api/process")
async def process_endpoint(
    files: list[UploadFile] = File(...),
    target_duration: float = Form(...),
    transition_duration: float = Form(...),
    output_filename: str = Form(...),
    use_crossfade: str | None = Form(None),
) -> JSONResponse:
    try:
        check_ffmpeg_tools()
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    validate_inputs(files, target_duration, transition_duration, output_filename)
    crossfade_enabled = parse_bool(use_crossfade)
    session_id, upload_dir = save_uploads_to_session(files)
    job_id = f"job_{session_id}"

    set_job_status(
        job_id,
        state="queued",
        session_id=session_id,
        output_file=None,
        download_url=None,
        error=None,
        messages=["Upload completed. Waiting to start processing..."],
    )

    worker = threading.Thread(
        target=run_processing_job,
        args=(
            job_id,
            upload_dir,
            target_duration,
            transition_duration,
            output_filename,
            crossfade_enabled,
        ),
        daemon=True,
    )
    worker.start()
    return JSONResponse({"job_id": job_id})


@app.get("/api/status/{job_id}")
def status_endpoint(job_id: str) -> JSONResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        payload = dict(job)
    return JSONResponse(payload)


@app.get("/download/{file_name}")
def download_output(file_name: str) -> FileResponse:
    if Path(file_name).name != file_name:
        raise HTTPException(status_code=400, detail="Invalid file name.")
    if not file_name.lower().endswith(".mp4"):
        raise HTTPException(status_code=400, detail="Only MP4 downloads are allowed.")

    candidate = (OUTPUTS_ROOT / file_name).resolve()
    outputs_root_resolved = OUTPUTS_ROOT.resolve()
    try:
        candidate.relative_to(outputs_root_resolved)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsafe file path.") from exc

    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Output file not found.")

    return FileResponse(
        path=str(candidate),
        media_type="video/mp4",
        filename=file_name,
    )
