from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Callable
from uuid import uuid4


FPS = 30
CRF = "20"
PRESET = "medium"
MIN_TRANSITION_FLOOR = 0.05
STDERR_TAIL_LINES = 25
OVERLAY_TEXT_MAX_LENGTH = 120
OVERLAY_FONT_MIN = 12
OVERLAY_FONT_MAX = 120
OVERLAY_ALLOWED_PLACEMENTS = {
    "upper left",
    "upper center",
    "upper right",
    "center",
    "lower left",
    "lower center",
    "lower right",
}


class ProcessingError(Exception):
    """Raised when video processing cannot continue safely."""


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    duration: float
    width: int
    height: int


@dataclass(frozen=True)
class TextOverlay:
    text: str
    start_time: float
    end_time: float
    placement: str
    font_size: int


def check_ffmpeg_tools() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise ProcessingError(
            "FFmpeg is required but was not found in PATH. Install FFmpeg and ensure "
            "both `ffmpeg` and `ffprobe` commands are available in your shell."
        )
    return ffmpeg, ffprobe


def natural_sort_paths(paths: list[Path]) -> list[Path]:
    split_re = re.compile(r"(\d+)")
    has_number_re = re.compile(r"\d")

    def key_func(path: Path) -> tuple[int, object]:
        name = path.name.lower()
        if not has_number_re.search(name):
            # Fallback for names without numbers: normal lowercase lexical sort.
            return (1, name)
        chunks = split_re.split(name)
        natural_key = tuple(int(chunk) if chunk.isdigit() else chunk for chunk in chunks)
        return (0, natural_key)

    return sorted(paths, key=key_func)


def safe_output_name(raw_name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name.strip())
    clean = clean.strip("._")
    if not clean:
        clean = "timelapse"
    if not clean.lower().endswith(".mp4"):
        clean += ".mp4"
    return clean


def choose_output_path(outputs_dir: Path, output_name: str) -> Path:
    base_name = safe_output_name(output_name)
    candidate = outputs_dir / base_name
    if not candidate.exists():
        return candidate
    stem = Path(base_name).stem
    return outputs_dir / f"{stem}_{uuid4().hex[:8]}.mp4"


def validate_text_overlays_payload(payload: Any) -> list[TextOverlay]:
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ProcessingError("Overlay configuration must be a JSON list.")

    validated: list[TextOverlay] = []
    for idx, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            raise ProcessingError(f"Overlay row {idx} is invalid.")

        raw_text = str(row.get("text", "")).strip()
        if not raw_text:
            # Ignore completely empty rows.
            continue
        if len(raw_text) > OVERLAY_TEXT_MAX_LENGTH:
            raise ProcessingError(
                f"Overlay row {idx}: text is too long (max {OVERLAY_TEXT_MAX_LENGTH} characters)."
            )

        try:
            start_time = float(row.get("start_time", 0))
            end_time = float(row.get("end_time", 0))
        except (TypeError, ValueError) as exc:
            raise ProcessingError(f"Overlay row {idx}: start/end time must be numeric.") from exc

        if start_time < 0:
            raise ProcessingError(f"Overlay row {idx}: start time must be >= 0.")
        if end_time <= start_time:
            raise ProcessingError(f"Overlay row {idx}: end time must be greater than start time.")

        placement = str(row.get("placement", "")).strip().lower()
        if placement not in OVERLAY_ALLOWED_PLACEMENTS:
            raise ProcessingError(f"Overlay row {idx}: invalid placement '{placement}'.")

        try:
            font_size = int(row.get("font_size", 0))
        except (TypeError, ValueError) as exc:
            raise ProcessingError(f"Overlay row {idx}: font size must be an integer.") from exc
        if font_size < OVERLAY_FONT_MIN or font_size > OVERLAY_FONT_MAX:
            raise ProcessingError(
                f"Overlay row {idx}: font size must be between {OVERLAY_FONT_MIN} and {OVERLAY_FONT_MAX}."
            )

        validated.append(
            TextOverlay(
                text=raw_text,
                start_time=start_time,
                end_time=end_time,
                placement=placement,
                font_size=font_size,
            )
        )

    return validated


def overlay_position_expression(placement: str) -> tuple[str, str]:
    mapping = {
        "upper left": ("40", "40"),
        "upper center": ("(w-text_w)/2", "40"),
        "upper right": ("w-text_w-40", "40"),
        "center": ("(w-text_w)/2", "(h-text_h)/2"),
        "lower left": ("40", "h-text_h-40"),
        "lower center": ("(w-text_w)/2", "h-text_h-40"),
        "lower right": ("w-text_w-40", "h-text_h-40"),
    }
    try:
        return mapping[placement]
    except KeyError as exc:
        raise ProcessingError(f"Unsupported overlay placement: {placement}") from exc


def escape_drawtext_text(text: str) -> str:
    escaped = text.replace("\r", " ").replace("\n", " ")
    escaped = escaped.replace("\\", "\\\\")
    escaped = escaped.replace(":", r"\:")
    escaped = escaped.replace("'", r"\'")
    escaped = escaped.replace("%", r"\%")
    escaped = escaped.replace(",", r"\,")
    return escaped


def _escape_drawtext_path(path: Path) -> str:
    value = str(path)
    value = value.replace("\\", "\\\\")
    value = value.replace(":", r"\:")
    value = value.replace("'", r"\'")
    return value


def _find_fontfile_for_drawtext() -> Path | None:
    candidate = Path(r"C:\Windows\Fonts\arial.ttf")
    if candidate.exists():
        return candidate
    return None


def _summarize_stderr(text: str, limit: int = STDERR_TAIL_LINES) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "No stderr output was produced by FFmpeg."
    return "\n".join(lines[-limit:])


def _run_command(cmd: list[str], error_context: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr or result.stdout or ""
        command_text = " ".join(cmd)
        summary = _summarize_stderr(stderr)
        raise ProcessingError(
            f"{error_context}\nCommand: {command_text}\nFFmpeg output (tail):\n{summary}"
        )


def probe_video(ffprobe_path: str, video_path: Path) -> VideoInfo:
    cmd = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        "format=duration:stream=width,height",
        "-select_streams",
        "v:0",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ProcessingError(f"FFprobe failed for {video_path.name}: {result.stderr.strip()}")

    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        duration = float(payload["format"]["duration"])
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, ValueError, IndexError, json.JSONDecodeError) as exc:
        raise ProcessingError(f"Could not read metadata for {video_path.name}.") from exc

    if duration <= 0:
        raise ProcessingError(f"Invalid duration in {video_path.name}.")
    return VideoInfo(path=video_path, duration=duration, width=width, height=height)


def _even(value: int) -> int:
    if value < 2:
        return 2
    return value if value % 2 == 0 else value - 1


def _normalize_clip(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    target_width: int,
    target_height: int,
    speed_factor: float,
) -> None:
    vf = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fps={FPS},settb=AVTB,setsar=1,setpts=PTS/{speed_factor:.10f},format=yuv420p"
    )
    cmd = [
        ffmpeg_path,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        vf,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        PRESET,
        "-crf",
        CRF,
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    _run_command(cmd, f"Normalization failed for {input_path.name}.")


def _combine_with_cuts(
    ffmpeg_path: str,
    normalized_files: list[Path],
    output_path: Path,
) -> None:
    cmd: list[str] = [ffmpeg_path, "-y"]
    for path in normalized_files:
        cmd.extend(["-i", str(path)])
    concat_inputs = "".join(f"[{idx}:v]" for idx in range(len(normalized_files)))
    filter_complex = f"{concat_inputs}concat=n={len(normalized_files)}:v=1:a=0[vout]"
    cmd.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            PRESET,
            "-crf",
            CRF,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    _run_command(cmd, "Failed to concatenate clips with cuts.")


def _combine_with_crossfade(
    ffmpeg_path: str,
    normalized_files: list[Path],
    sped_durations: list[float],
    transition_duration: float,
    output_path: Path,
) -> None:
    cmd: list[str] = [ffmpeg_path, "-y"]
    for path in normalized_files:
        cmd.extend(["-i", str(path)])

    # Build xfade chain progressively. Each transition offset is relative to
    # the current composited stream and starts at:
    # current_composite_duration - transition_duration.
    filter_parts: list[str] = []
    current_duration = sped_durations[0]
    prev_label = "[0:v]"
    for idx in range(1, len(normalized_files)):
        next_label = f"[v{idx}]"
        offset = max(current_duration - transition_duration, 0.0)
        part = (
            f"{prev_label}[{idx}:v]xfade=transition=fade:"
            f"duration={transition_duration:.3f}:offset={offset:.3f}{next_label}"
        )
        filter_parts.append(part)
        prev_label = next_label
        current_duration = current_duration + sped_durations[idx] - transition_duration

    final_map = prev_label
    cmd.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            final_map,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            PRESET,
            "-crf",
            CRF,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    _run_command(cmd, "Failed to combine clips with crossfade transitions.")


def _build_drawtext_filter(text_overlays: list[TextOverlay]) -> str:
    fontfile = _find_fontfile_for_drawtext()
    filters: list[str] = []
    for overlay in text_overlays:
        x_expr, y_expr = overlay_position_expression(overlay.placement)
        escaped_text = escape_drawtext_text(overlay.text)
        parts = [
            "fontcolor=white",
            "box=1",
            "boxcolor=black@0.55",
            "boxborderw=12",
            f"fontsize={overlay.font_size}",
            f"x={x_expr}",
            f"y={y_expr}",
            f"enable='between(t,{overlay.start_time:.3f},{overlay.end_time:.3f})'",
            f"text='{escaped_text}'",
        ]
        if fontfile:
            parts.append(f"fontfile='{_escape_drawtext_path(fontfile)}'")
        filters.append("drawtext=" + ":".join(parts))
    return ",".join(filters)


def _apply_text_overlays(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    text_overlays: list[TextOverlay],
) -> None:
    filter_chain = _build_drawtext_filter(text_overlays)
    cmd = [
        ffmpeg_path,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        filter_chain,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        PRESET,
        "-crf",
        CRF,
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    _run_command(cmd, "Failed to apply text overlays.")


def _calculate_safe_transition(
    requested_transition: float,
    clip_durations: list[float],
) -> tuple[float, str | None]:
    if requested_transition <= 0:
        return 0.0, None
    shortest = min(clip_durations)
    max_safe = max(shortest - MIN_TRANSITION_FLOOR, 0.0)
    if max_safe <= MIN_TRANSITION_FLOOR:
        return (
            0.0,
            "Crossfade disabled automatically because clips are too short after speed-up.",
        )
    if requested_transition <= max_safe:
        return requested_transition, None
    return (
        max_safe,
        (
            "Transition duration was reduced automatically "
            f"from {requested_transition:.3f}s to {max_safe:.3f}s to stay safe."
        ),
    )


def process_timelapse(
    input_files: list[Path],
    output_path: Path,
    target_duration: float,
    transition_duration: float,
    use_crossfade: bool,
    text_overlays: list[TextOverlay] | None = None,
    status_callback: Callable[[str], None] | None = None,
    debug_mode: bool = False,
    temp_root: Path | None = None,
) -> Path:
    def update(message: str) -> None:
        if status_callback:
            status_callback(message)

    if len(input_files) < 2:
        raise ProcessingError("At least 2 MP4 clips are required.")
    if target_duration <= 0:
        raise ProcessingError("Target duration must be a positive number of seconds.")

    ffmpeg_path, ffprobe_path = check_ffmpeg_tools()
    sorted_files = natural_sort_paths(input_files)
    video_infos = [probe_video(ffprobe_path, p) for p in sorted_files]

    target_width = _even(video_infos[0].width)
    target_height = _even(video_infos[0].height)
    total_source_duration = sum(v.duration for v in video_infos)

    # Required timelapse factor:
    # speed_factor = total_source_duration / target_duration
    speed_factor = total_source_duration / target_duration
    if speed_factor <= 0:
        raise ProcessingError("Could not compute a valid speed factor.")

    update(f"Using target resolution {target_width}x{target_height} at {FPS} fps.")
    update(f"Calculated speed factor: {speed_factor:.4f}x.")
    update(
        f"Total source duration: {total_source_duration:.2f}s. "
        f"Requested target duration: {target_duration:.2f}s."
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    working_parent = temp_root if temp_root else output_path.parent
    working_parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(mkdtemp(prefix="vtl_", dir=str(working_parent)))
    overlay_rows = text_overlays or []
    normalized_files: list[Path] = []
    try:
        for idx, info in enumerate(video_infos, start=1):
            normalized = temp_dir / f"normalized_{idx:04d}.mp4"
            update(f"Normalizing clip {idx}/{len(video_infos)}: {info.path.name}")
            _normalize_clip(
                ffmpeg_path=ffmpeg_path,
                input_path=info.path,
                output_path=normalized,
                target_width=target_width,
                target_height=target_height,
                speed_factor=speed_factor,
            )
            normalized_files.append(normalized)

        normalized_infos = [probe_video(ffprobe_path, clip) for clip in normalized_files]
        normalized_durations = [info.duration for info in normalized_infos]
        requested_crossfade = use_crossfade and len(normalized_files) > 1 and transition_duration > 0
        can_crossfade = requested_crossfade
        effective_transition = transition_duration

        if requested_crossfade:
            effective_transition, warning = _calculate_safe_transition(
                requested_transition=transition_duration,
                clip_durations=normalized_durations,
            )
            if warning:
                update(f"Warning: {warning}")
            if effective_transition <= 0:
                can_crossfade = False

        base_output_path = output_path
        if overlay_rows:
            base_output_path = temp_dir / "timelapse_base.mp4"

        update("Combining normalized clips into final MP4.")
        if can_crossfade:
            try:
                _combine_with_crossfade(
                    ffmpeg_path=ffmpeg_path,
                    normalized_files=normalized_files,
                    sped_durations=normalized_durations,
                    transition_duration=effective_transition,
                    output_path=base_output_path,
                )
                predicted_duration = sum(normalized_durations) - effective_transition * (
                    len(normalized_durations) - 1
                )
                update(
                    "Crossfade mode enabled. "
                    f"Transition duration: {effective_transition:.3f}s."
                )
            except ProcessingError as exc:
                update(f"Warning: Crossfade failed, falling back to cuts. Reason: {exc}")
                _combine_with_cuts(
                    ffmpeg_path=ffmpeg_path,
                    normalized_files=normalized_files,
                    output_path=base_output_path,
                )
                predicted_duration = sum(normalized_durations)
        else:
            if use_crossfade and transition_duration > 0:
                update("Warning: Falling back to cuts because crossfade is not safe for these clips.")
            _combine_with_cuts(
                ffmpeg_path=ffmpeg_path,
                normalized_files=normalized_files,
                output_path=base_output_path,
            )
            predicted_duration = sum(normalized_durations)

        if overlay_rows:
            update("Applying text overlays...")
            _apply_text_overlays(
                ffmpeg_path=ffmpeg_path,
                input_path=base_output_path,
                output_path=output_path,
                text_overlays=overlay_rows,
            )
        else:
            update("No text overlays requested.")

        update(
            "Estimated final duration: "
            f"{predicted_duration:.2f}s (requested: {target_duration:.2f}s)."
        )
        update("Final timelapse MP4 created.")
        return output_path
    finally:
        if debug_mode:
            update(f"Debug mode enabled. Temporary files kept in: {temp_dir}")
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)


def process_videos(
    input_files: list[Path],
    outputs_dir: Path,
    temp_dir: Path,
    output_name: str,
    target_duration: float,
    transition_duration: float,
    use_crossfade: bool,
    status_callback: Callable[[str], None] | None = None,
) -> Path:
    """
    Backward-compatible wrapper for previous API usage in app/main.py.
    """
    output_path = choose_output_path(outputs_dir, output_name)
    return process_timelapse(
        input_files=input_files,
        output_path=output_path,
        target_duration=target_duration,
        transition_duration=transition_duration,
        use_crossfade=use_crossfade,
        status_callback=status_callback,
        temp_root=temp_dir,
    )
