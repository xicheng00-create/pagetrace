"""FIFO, single-process worker for externally installed VideoKit."""

import logging
import os
import shutil
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path

from services.video_cards import concept_card_ids, due_card_ids, neighbours, render_context

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]


def tighten(cmd):
    """把 --max-chars 收到 3/4：导演超配额时唯一的可用旋钮，下限 600 字。"""
    out = list(cmd)
    if "--max-chars" in out:
        i = out.index("--max-chars") + 1
        out[i] = str(max(600, int(out[i]) * 3 // 4))
    return out


def prewarm_today(app):
    with app.app_context():
        from data.db import get_db
        from services.clock import now_iso

        con = get_db()
        today = date.today().isoformat()
        owner = con.execute("SELECT id FROM users WHERE role='owner' ORDER BY id LIMIT 1").fetchone()
        if not owner:
            return 0
        user_id = owner["id"]
        if con.execute(
            "SELECT 1 FROM card_video_daily_runs WHERE date=? AND user_id=?", (today, user_id)
        ).fetchone():
            return 0
        ids = due_card_ids(con, user_id, 30)
        queued = 0
        for item in ids:
            card_id = item["id"]
            card = render_context(con, card_id)
            if not card:
                continue
            existing = con.execute(
                "SELECT status FROM card_videos WHERE core_card_id=?", (card_id,)
            ).fetchone()
            if existing:
                continue
            cur = con.execute(
                "INSERT INTO card_videos(core_card_id,concept_id,status,source,requested_at,requested_by) VALUES(?,?,'queued','prewarm',?,?)",
                (card_id, card["concept_id"], now_iso(), user_id),
            )
            for peer in concept_card_ids(con, card["concept_id"]):
                con.execute(
                    "INSERT OR IGNORE INTO card_video_links(video_id,card_id,is_core) VALUES(?,?,?)",
                    (cur.lastrowid, peer["id"], int(peer["id"] == card_id)),
                )
            queued += 1
        con.execute(
            "INSERT INTO card_video_daily_runs(date,user_id,total,queued,skipped,ran_at) VALUES(?,?,?,?,?,?)",
            (today, user_id, len(ids), queued, max(0, len(ids) - queued), now_iso()),
        )
        con.commit()
        return queued


def _render(app, video):
    with app.app_context():
        from data.db import get_db

        con = get_db()
        card = render_context(con, video["core_card_id"])
        if not card:
            raise RuntimeError("card disappeared")
        peers = [r["front"] for r in neighbours(con, card["concept_id"], card["id"])]
    python = ROOT / ".venv/bin/python"
    dest = ROOT / "data-local/media/videos"
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="review-video-") as temp:
        temp = Path(temp)
        note = temp / "note.md"
        note.write_text(
            f"# {card['front']}\n概念：{card['concept_name']}\n答案：{card['back']}\n出处：{card['source']}\n只允许以上内容作为依据，不确定不要编造\n",
            encoding="utf-8",
        )
        script = temp / "card.json"
        project = temp / "project"
        out = temp / "out"
        clean_peers = [
            str(text).replace(",", " ").replace("，", " ").replace("\n", " ").replace("\r", " ")
            for text in peers[:6]
        ]
        neighbour_arg = "、".join(clean_peers)
        commands = [
            (
                [
                    str(python),
                    str(ROOT / "backend/video/director.py"),
                    "--page",
                    str(note),
                    "--out",
                    str(script),
                    "--title",
                    card["front"][:120],
                    "--source",
                    card["source"],
                    "--neighbours",
                    neighbour_arg,
                    "--tries",
                    "3",
                    # 单张卡的证据只有卡面本身，输入要压小、并要求紧凑稿：
                    # 实测不压时导演产出 576–653 字 / 15 场，必被 VideoKit 的 440–500 字闸门拒。
                    "--max-chars",
                    "1200",
                    "--tight",
                ],
                600,
            ),
            (
                [
                    str(python),
                    str(ROOT / "backend/video/pipeline.py"),
                    str(script),
                    "--project",
                    str(project),
                    "--out-dir",
                    str(out),
                    "--name-prefix",
                    str(video["id"]),
                ],
                1200,
            ),
        ]

        def run(cmd, timeout):
            result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=timeout)
            if result.returncode:
                raise RuntimeError((result.stdout + "\n" + result.stderr)[-600:])

        director_cmd, director_timeout = commands[0]
        try:
            run(director_cmd, director_timeout)
        except RuntimeError as exc:
            # VideoKit 的导演闸门把配音压到 440–500 字；首稿仍可能超配额（实测 576–653 字 ≈ 118–133 秒）。
            # 只有失败原因带「超出」才值得收紧重试，别对别类错误盲目重跑（白烧 token）。
            if "超出" not in str(exc):
                raise
            logger.warning("director over quota, tighten: %s", str(exc)[-160:])
            run(tighten(director_cmd), director_timeout)
        run(*commands[1])
        files = list(out.glob("*.mp4"))
        if len(files) != 1:
            raise RuntimeError("renderer must produce exactly one mp4")
        target = files[0]
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(target),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
        if probe.returncode:
            raise RuntimeError((probe.stdout + "\n" + probe.stderr)[-600:])
        duration = float(probe.stdout.strip())
        if not 60 <= duration <= 120:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"duration out of range: {duration}s")
        final = dest / f"{video['id']}.mp4"
        shutil.move(str(target), final)
        return final.name, duration, final.stat().st_size


def run_once(app):
    with app.app_context():
        from data.db import get_db

        con = get_db()
        row = con.execute("SELECT * FROM card_videos WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return False
        con.execute("UPDATE card_videos SET status='generating' WHERE id=?", (row["id"],))
        con.commit()
        try:
            name, duration, size = _render(app, dict(row))
            from services.clock import now_iso

            con.execute(
                "UPDATE card_videos SET status='ready',file_name=?,duration_s=?,size_bytes=?,ready_at=?,error=NULL WHERE id=?",
                (name, duration, size, now_iso(), row["id"]),
            )
        except Exception as exc:
            logger.exception("video generation failed id=%s", row["id"])
            con.execute(
                "UPDATE card_videos SET status='failed',error=? WHERE id=?", (str(exc)[:1000], row["id"])
            )
        con.commit()
        return True


def recover_generating(app):
    with app.app_context():
        from data.db import get_db

        con = get_db()
        cursor = con.execute("UPDATE card_videos SET status='queued' WHERE status='generating'")
        con.commit()
        return cursor.rowcount


def serve(app):
    recover_generating(app)
    yesterday = None
    prewarm = os.environ.get("VIDEO_PREWARM_ENABLED", "1") != "0"
    while True:
        try:
            today = date.today()
            if prewarm and today != yesterday:
                prewarm_today(app)
                yesterday = today
            run_once(app)
        except Exception:
            logger.exception("video worker loop failed")
        time.sleep(5)


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from app import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = create_app()
    if "--prewarm-once" in sys.argv:
        # 夜间预热：只入队不渲染，交由常驻 worker 排队消化，避免白天和交互抢 CPU。
        print(prewarm_today(app))
        raise SystemExit(0)
    serve(app)
