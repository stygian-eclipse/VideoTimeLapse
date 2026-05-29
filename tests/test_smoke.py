from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import app.main as main_module
from app.main import app
from app.video_processor import (
    ProcessingError,
    escape_drawtext_text,
    natural_sort_paths,
    overlay_position_expression,
    safe_output_name,
    validate_text_overlays_payload,
)


@pytest.fixture(autouse=True)
def isolate_auto_shutdown_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VTL_DISABLE_AUTO_SHUTDOWN", "1")
    main_module.auto_shutdown_started = False
    main_module.shutdown_initiated = False
    main_module.record_heartbeat()


def test_safe_output_name_enforces_mp4() -> None:
    assert safe_output_name("my clip") == "my_clip.mp4"
    assert safe_output_name("final.MP4").lower() == "final.mp4"
    assert safe_output_name("..") == "timelapse.mp4"


def test_natural_sort_paths_numeric_order() -> None:
    items = [
        Path("10.mp4"),
        Path("2.mp4"),
        Path("clip_10.mp4"),
        Path("clip_2.mp4"),
        Path("clip_1.mp4"),
        Path("1.mp4"),
    ]
    sorted_names = [p.name for p in natural_sort_paths(items)]
    assert sorted_names == [
        "1.mp4",
        "2.mp4",
        "10.mp4",
        "clip_1.mp4",
        "clip_2.mp4",
        "clip_10.mp4",
    ]


def test_health_endpoint_returns_json() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "ffmpeg_available" in payload


def test_heartbeat_endpoint_returns_ok() -> None:
    client = TestClient(app)
    response = client.post("/api/heartbeat")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_overlay_validation_accepts_and_ignores_empty_rows() -> None:
    payload = [
        {
            "text": "  #BeforeForever ",
            "start_time": 0,
            "end_time": 4.5,
            "placement": "lower center",
            "font_size": 36,
        },
        {
            "text": "   ",
            "start_time": 1,
            "end_time": 2,
            "placement": "center",
            "font_size": 20,
        },
    ]
    overlays = validate_text_overlays_payload(payload)
    assert len(overlays) == 1
    assert overlays[0].text == "#BeforeForever"
    assert overlays[0].placement == "lower center"


def test_escape_drawtext_text_escapes_reserved_chars() -> None:
    source = r"Hi #tag @name 100%: it's \ok, yes"
    escaped = escape_drawtext_text(source)
    assert r"\%" in escaped
    assert r"\:" in escaped
    assert r"\'" in escaped
    assert r"\\" in escaped
    assert r"\," in escaped


def test_overlay_position_expression_values() -> None:
    assert overlay_position_expression("upper left") == ("40", "40")
    assert overlay_position_expression("center") == ("(w-text_w)/2", "(h-text_h)/2")
    assert overlay_position_expression("lower right") == ("w-text_w-40", "h-text_h-40")


def test_overlay_validation_rejects_invalid_interval() -> None:
    payload = [
        {
            "text": "Out now",
            "start_time": 3,
            "end_time": 2,
            "placement": "lower center",
            "font_size": 36,
        }
    ]
    with pytest.raises(ProcessingError):
        validate_text_overlays_payload(payload)


def test_has_active_jobs_detects_queued_and_running() -> None:
    with main_module.jobs_lock:
        main_module.jobs.clear()
        main_module.jobs["a"] = {"state": "completed"}
    assert main_module.has_active_jobs() is False

    with main_module.jobs_lock:
        main_module.jobs["b"] = {"state": "queued"}
    assert main_module.has_active_jobs() is True

    with main_module.jobs_lock:
        main_module.jobs["b"] = {"state": "running"}
    assert main_module.has_active_jobs() is True

    with main_module.jobs_lock:
        main_module.jobs.clear()


def test_auto_shutdown_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VTL_DISABLE_AUTO_SHUTDOWN", "1")
    main_module.auto_shutdown_started = False
    started = main_module.start_auto_shutdown_monitor_if_enabled()
    assert started is False
    assert main_module.is_auto_shutdown_disabled() is True
