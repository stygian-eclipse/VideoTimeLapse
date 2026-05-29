# VideoTimeLapse

VideoTimeLapse is a local web utility that combines multiple MP4 clips into one timelapse MP4 file.

Generated videos are **silent by design** (no audio track), so you can add your own music later.

## Requirements

- Python 3.11+
- FFmpeg and FFprobe available in PATH (`ffmpeg` and `ffprobe`)

## Install FFmpeg on Windows

Recommended:

```powershell
winget install Gyan.FFmpeg
```

Or install FFmpeg manually and add its `bin` folder to PATH.

## Quick Start on Windows (Recommended)

1. Clone the repository:

```powershell
git clone https://github.com/stygian-eclipse/VideoTimeLapse.git
cd VideoTimeLapse
```

2. Run the launcher:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_timelapse_maker.ps1
```

This script will:
- Create `.venv` if missing
- Install dependencies from `requirements.txt`
- Start the local FastAPI server
- Open your browser automatically at `http://127.0.0.1:8000`
- Keep the terminal open so you can see logs

## Manual Developer Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Usage

1. Select at least 2 MP4 clips.
2. Use filenames like `1.mp4`, `2.mp4`, `10.mp4` for predictable order.
3. Choose target output duration (5-300 seconds).
4. Choose transition duration (0-3 seconds).
5. Generate and download the final MP4.

## Output Behavior

- Clips are sorted naturally by filename before processing
- All clips are sped up to fit the requested target duration
- Crossfades are applied when enabled (with safe fallback to cuts)
- Final output is a silent MP4 (H.264, browser-downloadable)

## Troubleshooting

- PowerShell execution policy:
  - If scripts are blocked, run:
  - `powershell -ExecutionPolicy Bypass -File .\run_timelapse_maker.ps1`
- FFmpeg not found:
  - Check `ffmpeg -version` and `ffprobe -version`
  - Install with `winget install Gyan.FFmpeg` and reopen PowerShell
- Browser does not open automatically:
  - Open `http://127.0.0.1:8000` manually
- Output duration slightly different:
  - Small differences can happen due to frame rounding
- Crossfade too long:
  - Transition duration may be reduced automatically, or fallback to cuts
- Large files take time:
  - Processing is CPU-intensive and may take several minutes

## Project Structure

```text
app/
  main.py
  video_processor.py
  templates/
    index.html
  static/
    style.css
    app.js

work/
  uploads/
  outputs/
  temp/

run_timelapse_maker.ps1
run_app.py
requirements.txt
README.md
.gitignore
```

## API Endpoints

- `GET /` - Web UI
- `GET /health` - Health and FFmpeg availability
- `POST /api/process` - Start processing job
- `GET /api/status/{job_id}` - Poll job status
- `GET /download/{file_name}` - Download generated MP4

## Validation

Run a quick smoke test:

```powershell
python -m pytest tests/test_smoke.py
```
