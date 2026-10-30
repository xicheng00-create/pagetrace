import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
import video_worker  # noqa: E402
from data.db import get_db  # noqa: E402
from video_worker import prewarm_today, recover_generating, run_once  # noqa: E402


@contextmanager
def _tempdir(path):
    yield str(path)


def _queue(video_client):
    with video_client.application.app_context():
        con = get_db()
        con.executescript("""
        INSERT INTO users(username,password_hash,role,created_at) VALUES('owner','x','owner',datetime('now'));
        INSERT INTO subjects(name,slug,created_at) VALUES('s','s',datetime('now'));
        INSERT INTO books(subject_id,title,slug,status,created_at,owner_id) VALUES(1,'b','b','active',datetime('now'),1);
        INSERT INTO chapters(book_id,name,anchor,unlocked_at,status) VALUES(1,'c','c',datetime('now'),'active');
        INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('a',1,'a');
        INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,created_at,title) VALUES(1,1,'front','back','source','hash',datetime('now'),'title');
        INSERT INTO card_videos(core_card_id,concept_id,status,source,requested_at) VALUES(1,1,'queued','manual',datetime('now'));
        INSERT INTO card_video_links(video_id,card_id,is_core) VALUES(1,1,1);
        """)
        con.commit()


def test_worker_failure_logged(video_client, monkeypatch, caplog):
    _queue(video_client)
    monkeypatch.setattr("video_worker._render", lambda app, row: (_ for _ in ()).throw(RuntimeError("simulated renderer error")))
    assert run_once(video_client.application)
    with video_client.application.app_context():
        row = get_db().execute("SELECT status,error FROM card_videos").fetchone()
        assert row["status"] == "failed" and "simulated renderer error" in row["error"]
    assert "video generation failed" in caplog.text


def test_worker_empty_queue(video_client):
    assert run_once(video_client.application) is False


def test_worker_ready_persists(video_client, monkeypatch):
    _queue(video_client)
    monkeypatch.setattr("video_worker._render", lambda app, row: ("done.mp4", 90.0, 123))
    assert run_once(video_client.application)
    with video_client.application.app_context():
        row = get_db().execute("SELECT status,file_name,duration_s,size_bytes,ready_at FROM card_videos").fetchone()
        assert row["status"] == "ready" and row["file_name"] == "done.mp4"
        assert row["duration_s"] == 90 and row["size_bytes"] == 123 and row["ready_at"]


def test_worker_error_truncated(video_client, monkeypatch):
    _queue(video_client)
    monkeypatch.setattr("video_worker._render", lambda app, row: (_ for _ in ()).throw(RuntimeError("x" * 1400)))
    assert run_once(video_client.application)
    with video_client.application.app_context():
        row = get_db().execute("SELECT status,error FROM card_videos").fetchone()
        assert row["status"] == "failed" and len(row["error"]) == 1000


def test_render_success_with_mock_processes(video_client, monkeypatch, tmp_path):
    _queue(video_client)
    output_dir = tmp_path / "media"
    monkeypatch.setattr(video_worker, "ROOT", tmp_path)
    monkeypatch.setattr(video_worker.tempfile, "TemporaryDirectory", lambda **kw: _tempdir(tmp_path / "work"))
    work = tmp_path / "work"
    (work / "out").mkdir(parents=True)
    captured = []

    def fake_run(args, **kwargs):
        captured.append(args)
        if args[0] == "ffprobe":
            return SimpleNamespace(returncode=0, stdout="90.0", stderr="")
        if "director.py" in str(args):
            note = Path(args[args.index("--page") + 1]).read_text()
            assert "# front" in note and "答案：back" in note and "出处：source" in note
            neighbour = args[args.index("--neighbours") + 1]
            assert "bad, peer" not in neighbour and "bad，peer" not in neighbour and "\n" not in neighbour
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        (work / "out" / "result.mp4").write_bytes(b"video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(video_worker.subprocess, "run", fake_run)
    # Mock the move and stat destination to avoid writing repository media.
    monkeypatch.setattr(video_worker, "neighbours", lambda *a: [{"front": "bad, peer\nbad，peer"}] * 7)
    monkeypatch.setattr(video_worker.shutil, "move", lambda src, dst: Path(dst).write_bytes(b"video"))
    original_stat = Path.stat
    monkeypatch.setattr(Path, "stat", lambda self, *args, **kwargs: SimpleNamespace(st_size=5) if self.name == "1.mp4" else original_stat(self, *args, **kwargs))
    result = video_worker._render(video_client.application, {"id": 1, "core_card_id": 1})
    assert result == ("1.mp4", 90.0, 5)
    assert len([c for c in captured if "director.py" in str(c)]) == 1


def test_render_duration_59_fails_and_deletes(video_client, monkeypatch, tmp_path):
    _queue(video_client)
    monkeypatch.setattr(video_worker, "ROOT", tmp_path)
    work = tmp_path / "work"
    (work / "out").mkdir(parents=True)
    monkeypatch.setattr(video_worker.tempfile, "TemporaryDirectory", lambda **kw: _tempdir(work))
    target = work / "out" / "result.mp4"
    deleted = []
    original_unlink = Path.unlink
    monkeypatch.setattr(Path, "unlink", lambda self, **kw: deleted.append(self.name) if self == target else original_unlink(self, **kw))
    monkeypatch.setattr(video_worker.subprocess, "run", lambda args, **kw: SimpleNamespace(returncode=0, stdout="59", stderr=""))
    # Director and pipeline succeed; create the sole mp4 during pipeline invocation.
    calls = iter(("director", "pipeline", "ffprobe"))
    def staged_run(args, **kw):
        phase = next(calls)
        if phase == "pipeline": target.write_bytes(b"x")
        if phase == "ffprobe": return SimpleNamespace(returncode=0, stdout="59", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(video_worker.subprocess, "run", staged_run)
    try:
        video_worker._render(video_client.application, {"id": 1, "core_card_id": 1})
    except RuntimeError as exc:
        assert "duration out of range: 59" in str(exc)
    else:
        raise AssertionError("59 seconds must fail")
    assert "result.mp4" in deleted


def test_render_subprocess_failure_includes_log_tail(video_client, monkeypatch, tmp_path):
    _queue(video_client)
    monkeypatch.setattr(video_worker, "ROOT", tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(video_worker.tempfile, "TemporaryDirectory", lambda **kw: _tempdir(work))
    monkeypatch.setattr(video_worker.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=3, stdout="out", stderr="stderr-tail"))
    try:
        video_worker._render(video_client.application, {"id": 1, "core_card_id": 1})
    except RuntimeError as exc:
        assert "out" in str(exc) and "stderr-tail" in str(exc)
    else:
        raise AssertionError("renderer failure expected")


def test_prewarm_daily_idempotence(video_client):
    _queue(video_client)
    assert prewarm_today(video_client.application) == 0
    with video_client.application.app_context():
        con = get_db()
        runs = con.execute("SELECT count(*) FROM card_video_daily_runs").fetchone()[0]
        rows = con.execute("SELECT count(*) FROM card_videos").fetchone()[0]
    assert prewarm_today(video_client.application) == 0
    with video_client.application.app_context():
        con = get_db()
        assert con.execute("SELECT count(*) FROM card_video_daily_runs").fetchone()[0] == runs
        assert con.execute("SELECT count(*) FROM card_videos").fetchone()[0] == rows


def test_prewarm_without_owner(video_client):
    assert prewarm_today(video_client.application) == 0


def test_worker_recovers_stranded_generating(video_client):
    _queue(video_client)
    with video_client.application.app_context():
        get_db().execute("UPDATE card_videos SET status='generating'")
        get_db().commit()
    assert recover_generating(video_client.application) == 1
    with video_client.application.app_context():
        assert get_db().execute("SELECT status FROM card_videos").fetchone()["status"] == "queued"


def test_serve_recovers_before_first_loop(video_client, monkeypatch):
    _queue(video_client)
    with video_client.application.app_context():
        get_db().execute("UPDATE card_videos SET status='generating'")
        get_db().commit()
    seen = []
    monkeypatch.setattr(video_worker, "prewarm_today", lambda app: seen.append("prewarm"))
    monkeypatch.setattr(video_worker, "run_once", lambda app: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(video_worker.time, "sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        video_worker.serve(video_client.application)
    except KeyboardInterrupt:
        pass
    with video_client.application.app_context():
        assert get_db().execute("SELECT status FROM card_videos").fetchone()["status"] == "queued"
    assert seen == ["prewarm"]


def test_tighten_shrinks_max_chars():
    """导演超配额时的收紧旋钮：1200→900，且不低于 600。"""
    assert video_worker.tighten(["d.py", "--max-chars", "1200"]) == ["d.py", "--max-chars", "900"]
    assert video_worker.tighten(["d.py", "--max-chars", "700"])[-1] == "600"
    assert video_worker.tighten(["d.py"]) == ["d.py"]
