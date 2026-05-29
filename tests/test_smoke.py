from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.video_processor import natural_sort_paths, safe_output_name


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
