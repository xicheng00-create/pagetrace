import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))



def test_media_range_and_missing(video_client):
    root = Path(video_client.application.root_path).parent / "data-local/media/videos"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "test-range.mp4"
    path.write_bytes(b"abcdefgh")
    response = video_client.get("/media/videos/test-range.mp4", headers={"Range": "bytes=2-5"})
    assert response.status_code == 206 and response.headers["Content-Range"].startswith("bytes 2-5/8")
    assert "conditional=True" in (BACKEND / "api/videos.py").read_text()
    assert video_client.get("/media/videos/not-found.mp4").status_code == 404
