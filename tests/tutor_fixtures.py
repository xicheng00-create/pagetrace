"""Tutor 测试共用：两户种子数据 + app 构造（不依赖 conftest 的 legacy fixture）。"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# 户 1：owner / Ann（共享书 A，演示学科）；户 2：Bob（书 B，别的学科）
SEED = """
INSERT INTO users(username,password_hash,role,household_id,created_at) VALUES
  ('owner','x','owner',1,datetime('now')),
  ('Ann','x','member',1,datetime('now')),
  ('Bob','x','owner',2,datetime('now'));
INSERT INTO subjects(name,slug,created_at) VALUES('演示学科','psy',datetime('now')),('别的','oth',datetime('now'));
INSERT INTO books(subject_id,title,slug,status,created_at,owner_id) VALUES
  (1,'书A','a','active',datetime('now'),1),(2,'书B','b','active',datetime('now'),3);
INSERT INTO chapters(book_id,name,anchor,unlocked_at,status) VALUES
  (1,'第12章 权力与暴力','c1',datetime('now'),'active'),(2,'第1章 概论','c2',datetime('now'),'active');
INSERT INTO concepts(concept_uid,chapter_id,name,tags) VALUES
  ('u1',1,'亲密伴侣暴力','["概念"]'),('u2',1,'性满足','["概念"]'),('u3',2,'项目管理','["概念"]');
INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,created_at) VALUES
  (1,1,'亲密伴侣暴力包括哪些行为？','动手、威胁、恐吓、控制伴侣','src','h1',datetime('now')),
  (2,1,'性满足与关系满意度是什么关系？','床上不合会拉低关系满意度','src','h2',datetime('now')),
  (3,2,'项目组合是什么？','项目、项目集与组合的层次','src','h3',datetime('now'));
"""


def make_app(db_path, **config):
    from app import create_app

    app = create_app("development")
    app.config.update(TESTING=True, DATABASE_PATH=str(db_path), **config)
    with app.app_context():
        from data.db import get_db

        con = get_db()
        con.executescript(SEED)
        con.commit()
    return app


def token_for(app, username):
    """给指定用户签一个真 token（跨用户用例需要「不是当前请求的那一个」）。"""
    from auth import issue_token
    from data.db import get_db

    with app.app_context():
        user = get_db().execute(
            "SELECT id,username,role FROM users WHERE username=?", (username,)).fetchone()
    return issue_token(dict(user))


def bearer(token):
    return {"Authorization": f"Bearer {token}"}
