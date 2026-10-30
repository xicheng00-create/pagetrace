"""Optional narrated video API."""

import os
import shutil
from pathlib import Path

from data.db import get_db
from flask import Blueprint, current_app, g, jsonify, request, send_from_directory
from services import video_cards
from services.clock import now_iso
from services.video_cards import linked_cards, unlocked_card

bp = Blueprint("videos", __name__)
REASON = "未检测到 VideoKit（设置 VIDEOKIT_HOME）"
DEPS_REASON = "缺少渲染依赖：manim 或 edge-tts"


def _videokit_home():
    return Path(os.path.expanduser(os.environ.get("VIDEOKIT_HOME", "~/VideoKit")))


def _has(binary, fallback):
    """PATH 里找不到就退回安装时的绝对路径：web 进程的 PATH 不含 brain 的 venv。"""
    return bool(shutil.which(binary)) or Path(os.path.expanduser(fallback)).is_file()


def missing():
    """与 worker 同口径判可用：返回缺失项列表，空 = 可用。"""
    gaps = []
    if not (_videokit_home() / "videokit" / "cli.py").is_file():
        gaps.append("videokit")
    if not _has("manim", "~/.hermes/profiles/brain/workspace/venvs/manim312/bin/manim"):
        gaps.append("manim")
    if not _has("edge-tts", "~/.hermes/hermes-agent/venv/bin/edge-tts"):
        gaps.append("edge-tts")
    return gaps


def available():
    return not missing()


def reason():
    gaps = missing()
    if not gaps:
        return None
    return REASON if "videokit" in gaps else DEPS_REASON


def payload(data, status=200):
    """所有 JSON 接口统一 {code,data} 契约（前端 api.js 只认这个信封，
    视频接口早期直接返裸对象，导致 #/videos 与「讲解」按钮静默失败）。"""
    return jsonify({"code": 0, "data": data}), status


@bp.post("/api/videos/<int:video_id>/view")
def mark_viewed(video_id):
    """记一次「看过这个视频」（每日每片去重），供每日连胜判定。"""
    from services.clock import now
    con = get_db()
    uid = g.user_id
    vis = ("b.owner_id IN (SELECT u2.id FROM users u2 "
           "WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))")
    row = con.execute(
        "SELECT v.id FROM card_videos v JOIN concepts x ON x.id=v.concept_id "
        "JOIN chapters ch ON ch.id=x.chapter_id JOIN books b ON b.id=ch.book_id "
        "WHERE v.id=? AND " + vis, (video_id, uid)).fetchone()
    if not row:
        return jsonify({"code": 404, "msg": "视频不存在"}), 404
    at = now()
    con.execute("INSERT OR IGNORE INTO video_views(user_id,video_id,day,created_at) VALUES(?,?,?,?)",
                (uid, video_id, at.date().isoformat(), at.isoformat()))
    con.commit()
    done = con.execute("SELECT COUNT(*) FROM video_views WHERE user_id=? AND day=?",
                       (uid, at.date().isoformat())).fetchone()[0]
    from config import BaseConfig
    return payload({"viewed": True, "today": done, "target": BaseConfig.VIDEO_TASK_TARGET})


@bp.get("/api/videos/capability")
def capability():
    return payload({"available": available(), "reason": reason()})


def unlocked(con, card_id):
    return unlocked_card(con, card_id, g.user_id)


def enqueue(con, card, source="manual"):
    timestamp = now_iso()
    row = con.execute("SELECT id,status FROM card_videos WHERE core_card_id=?", (card["id"],)).fetchone()
    if row and row["status"] == "failed":
        con.execute(
            "UPDATE card_videos SET status='queued',error=NULL,source=?,requested_at=? WHERE id=?",
            (source, timestamp, row["id"]),
        )
        return "queued"
    if row:
        return row["status"]
    cur = con.execute(
        "INSERT INTO card_videos(core_card_id,concept_id,status,source,requested_at,requested_by) VALUES(?,?,'queued',?,?,?)",
        (card["id"], card["concept_id"], source, timestamp, g.user_id),
    )
    vid = cur.lastrowid
    for peer in video_cards.concept_card_ids(con, card["concept_id"]):
        con.execute(
            "INSERT OR IGNORE INTO card_video_links(video_id,card_id,is_core) VALUES(?,?,?)",
            (vid, peer["id"], int(peer["id"] == card["id"])),
        )
    return "queued"


@bp.post("/api/videos/request")
def video_request():
    card_id = (request.get_json(silent=True) or {}).get("card_id")
    con = get_db()
    card = unlocked(con, card_id)
    if not card:
        return jsonify({"code": 404, "msg": "资源不存在"}), 404
    if not available():
        return jsonify({"code": 503, "msg": REASON}), 503
    record = dict(card)
    record["id"] = card_id
    status = enqueue(con, record)
    con.commit()
    return payload({"status": status, "message": "已加入生成队列，完成后可在此播放"})


@bp.post("/api/videos/batch")
def batch():
    ids = (request.get_json(silent=True) or {}).get("card_ids", [])
    if not isinstance(ids, list):
        return jsonify({"code": 400, "msg": "card_ids 必须是数组"}), 400
    if len(ids) > 10:
        return jsonify({"code": 400, "msg": "一次最多 10 张"}), 400
    con = get_db()
    out = []
    for card_id in ids:
        card = unlocked(con, card_id)
        status = "unavailable"
        if card and available():
            record = dict(card)
            record["id"] = card_id
            status = enqueue(con, record, "batch")
        out.append({"card_id": card_id, "status": status})
    con.commit()
    return payload({"items": out})


@bp.get("/api/videos/state")
def state():
    con = get_db()
    card_id = request.args.get("card_id", type=int)
    if not card_id or not unlocked(con, card_id):
        return jsonify({"code": 404}), 404
    row = con.execute(
        "SELECT v.* FROM card_videos v JOIN card_video_links l ON l.video_id=v.id WHERE l.card_id=? ORDER BY v.id DESC LIMIT 1",
        (card_id,),
    ).fetchone()
    return payload(
        {
            "available": bool(available()),
            "video_id": row["id"] if row else None,
            "status": row["status"] if row else None,
            "url": "/media/videos/" + row["file_name"] if row and row["status"] == "ready" else None,
            "duration_s": row["duration_s"] if row else None,
            "requested_at": row["requested_at"] if row else None,
            "error": row["error"][:1000] if row and row["error"] else None,
        }
    )


@bp.get("/api/videos")
def videos():
    rows = get_db().execute(
        "SELECT v.id video_id,v.status,v.title,v.file_name,v.duration_s,b.title book_title,ch.name chapter_name,x.name concept_name FROM card_videos v JOIN concepts x ON x.id=v.concept_id JOIN chapters ch ON ch.id=x.chapter_id JOIN books b ON b.id=ch.book_id WHERE b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) AND v.status IN ('ready','queued') ORDER BY b.title,ch.order_no,x.name",
        (g.user_id,),
    )
    return payload({"items": [dict(row) for row in rows]})


@bp.get("/api/videos/<int:video_id>")
def detail(video_id):
    con = get_db()
    row = con.execute(
        "SELECT v.* FROM card_videos v JOIN concepts x ON x.id=v.concept_id JOIN chapters ch ON ch.id=x.chapter_id JOIN books b ON b.id=ch.book_id WHERE v.id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))",
        (video_id, g.user_id),
    ).fetchone()
    if not row:
        return jsonify({"code": 404}), 404
    links = linked_cards(con, video_id)
    result = dict(row)
    result["cards"] = [dict(item) for item in links]
    return payload(result)


@bp.get("/media/videos/<path:file>")
def media(file):
    return send_from_directory(
        Path(current_app.root_path).parent / "data-local/media/videos", file, conditional=True
    )
