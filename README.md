# VideoTimeLapse

VideoTimeLapse is a fully local Python utility with a browser UI that combines multiple MP4 clips into one silent timelapse MP4.  
It sorts clips naturally by filename (for example `1.mp4`, `2.mp4`, `10.mp4` and `clip_1.mp4`, `clip_2.mp4`, `clip_10.mp4`), speeds them up to match a target duration, and exports a downloadable final file.

Generated videos are **silent by design** so you can add music later in your preferred editor.

## Requirements

- Python 3.11+
- FFmpeg installed and available in PATH (`ffmpeg` and `ffprobe`)

## Windows FFmpeg Install

Option 1 (recommended with winget):

```powershell
winget install Gyan.FFmpeg
```

Option 2:

1. Download FFmpeg manually.
2. Extract it.
3. Add the FFmpeg `bin` folder to your Windows PATH.

## Setup

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Run the server:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open:

`http://127.0.0.1:8000`

## Usage

1. Open the local URL in your browser.
2. Select at least 2 `.mp4` files (for example `1.mp4`, `2.mp4`, `3.mp4`, `10.mp4`).
3. Set:
   - target output duration (5-300 seconds)
   - transition duration (0-3 seconds)
   - output filename
   - transition mode (crossfade or simple cuts)
4. Click **Generate Timelapse**.
5. Wait for status updates, then download the final MP4.

## What The App Does

- Validates uploads (MP4 only, minimum 2 files).
- Detects FFmpeg/FFprobe availability.
- Saves uploaded files in a unique timestamped session folder in `work/uploads/`.
- Sorts filenames naturally before processing.
- Probes source clip durations and dimensions using FFprobe.
- Normalizes clips to a shared format with FFmpeg:
  - based on first clip resolution
  - even dimensions for H.264 compatibility
  - preserved aspect ratio (scale + pad)
  - constant 30 fps
  - `yuv420p`
  - no audio
- Computes speed so all clips fit the requested target duration.
- Combines with crossfades or simple cuts.
  - If requested crossfade duration is too long after speed-up, it is reduced automatically.
  - If crossfade still cannot be applied safely, the app falls back to simple cuts and reports a warning.
- Exports final MP4/H.264 (`libx264`, `crf 20`, `preset medium`, `+faststart`) with no audio.

## API Endpoints

- `GET /` - Web UI
- `GET /health` - JSON health + FFmpeg availability
- `POST /api/process` - Start processing job
- `GET /api/status/{job_id}` - Poll processing status
- `GET /download/{file_name}` - Safe download for generated MP4

## Troubleshooting

- FFmpeg not found:
  - Confirm `ffmpeg -version` and `ffprobe -version` work in PowerShell.
  - Reopen terminal after changing PATH.
- Output duration slightly different:
  - Minor differences can happen from frame rounding during encoding.
- Crossfade too long:
  - The app auto-reduces transition duration when possible.
  - If clips are still too short, it falls back to cut mode automatically.
- Very large files take time:
  - Processing is CPU-intensive, especially with many clips and crossfades.

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

requirements.txt
README.md
.gitignore
```

## Local Run/Test Commands (PowerShell)

```powershell
cd c:\A_Various_AI_Projects_Tasks\VideoTimeLapse
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
ffmpeg -version
ffprobe -version
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
