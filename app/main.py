from __future__ import annotations

import json
import logging
import os
import signal
import shutil
import threading
import time
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
    TextOverlay,
    check_ffmpeg_tools,
    choose_output_path,
    process_timelapse,
    safe_output_name,
    validate_text_overlays_payload,
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
logger = logging.getLogger("videotimelapse")


jobs_lock = threading.Lock()
jobs: dict[str, dict[str, Any]] = {}
heartbeat_lock = threading.Lock()
auto_shutdown_lock = threading.Lock()
shutdown_lock = threading.Lock()
last_heartbeat_at = time.monotonic()
auto_shutdown_started = False
shutdown_initiated = False

HEARTBEAT_INTERVAL_SECONDS = 3
HEARTBEAT_TIMEOUT_SECONDS = 12
HEARTBEAT_MONITOR_CHECK_SECONDS = 2


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


def is_auto_shutdown_disabled() -> bool:
    return os.getenv("VTL_DISABLE_AUTO_SHUTDOWN", "").strip() == "1"


def record_heartbeat() -> float:
    now = time.monotonic()
    with heartbeat_lock:
        global last_heartbeat_at
        last_heartbeat_at = now
    return now


def heartbeat_age_seconds() -> float:
    with heartbeat_lock:
        return time.monotonic() - last_heartbeat_at


def has_active_jobs() -> bool:
    with jobs_lock:
        return any(job.get("state") in {"queued", "running"} for job in jobs.values())


def _request_server_shutdown() -> None:
    global shutdown_initiated
    with shutdown_lock:
        if shutdown_initiated:
            return
        shutdown_initiated = True

    def shutdown_worker() -> None:
        logger.warning("Shutting down server.")
        try:
            # Best effort graceful path for Uvicorn.
            os.kill(os.getpid(), signal.SIGINT)
            time.sleep(1.0)
        except Exception:  # noqa: BLE001
            pass
        # Fallback for local desktop utility: if graceful shutdown did not stop
        # the process, force-exit after a short delay.
        os._exit(0)

    threading.Thread(target=shutdown_worker, name="vtl-shutdown", daemon=True).start()


def _heartbeat_monitor_loop() -> None:
    logger.warning(
        "Heartbeat monitor started (interval=%ss timeout=%ss).",
        HEARTBEAT_MONITOR_CHECK_SECONDS,
        HEARTBEAT_TIMEOUT_SECONDS,
    )
    delay_logged = False
    while True:
        time.sleep(HEARTBEAT_MONITOR_CHECK_SECONDS)
        age = heartbeat_age_seconds()
        if age <= HEARTBEAT_TIMEOUT_SECONDS:
            delay_logged = False
            continue

        if has_active_jobs():
            if not delay_logged:
                logger.warning(
                    "Heartbeat timeout detected (age=%.1fs). Shutdown delayed because processing is active.",
                    age,
                )
                delay_logged = True
            continue

        logger.warning("Heartbeat timeout detected (age=%.1fs).", age)
        _request_server_shutdown()
        return


def start_auto_shutdown_monitor_if_enabled() -> bool:
    global auto_shutdown_started
    if is_auto_shutdown_disabled():
        logger.warning("Auto-shutdown disabled by VTL_DISABLE_AUTO_SHUTDOWN=1.")
        return False
    with auto_shutdown_lock:
        if auto_shutdown_started:
            return True
        auto_shutdown_started = True
    record_heartbeat()
    thread = threading.Thread(target=_heartbeat_monitor_loop, name="vtl-heartbeat-monitor", daemon=True)
    thread.start()
    return True


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
    text_overlays: list[TextOverlay],
) -> None:
    try:
        set_job_status(job_id, state="running")
        append_job_message(job_id, "Processing started.")
        input_files = [path for path in upload_dir.iterdir() if path.is_file() and path.suffix.lower() == ".mp4"]
        if len(input_files) < 2:
            raise ProcessingError("Less than 2 uploaded MP4 files were found after upload.")

        output_path = choose_output_path(OUTPUTS_ROOT, output_filename)
        output_path = process_timelapse(
            input_files=input_files,
            output_path=output_path,
            target_duration=target_duration,
            transition_duration=transition_duration,
            use_crossfade=use_crossfade,
            text_overlays=text_overlays,
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


@app.on_event("startup")
def startup_event() -> None:
    record_heartbeat()
    start_auto_shutdown_monitor_if_enabled()


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
    overlays_json: str | None = Form(None),
) -> JSONResponse:
    try:
        check_ffmpeg_tools()
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    validate_inputs(files, target_duration, transition_duration, output_filename)
    crossfade_enabled = parse_bool(use_crossfade)
    try:
        overlays_payload = json.loads(overlays_json) if overlays_json else []
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Overlay configuration is not valid JSON.") from exc
    try:
        text_overlays = validate_text_overlays_payload(overlays_payload)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            text_overlays,
        ),
        daemon=True,
    )
    worker.start()
    return JSONResponse({"job_id": job_id})


@app.post("/api/heartbeat")
def heartbeat_endpoint() -> JSONResponse:
    record_heartbeat()
    return JSONResponse({"status": "ok"})


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
