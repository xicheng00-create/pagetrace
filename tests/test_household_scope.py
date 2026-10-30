import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import create_app


def test_household_visibility_updates_after_moving_member(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "scope.sqlite3"))
    app=create_app("development")
    with app.app_context():
        from data.db import get_db
        from services.household import book_visibility_sql, member_ids
        con=get_db()
        con.execute("INSERT INTO users(username,password_hash,created_at) VALUES('Other','x','now')")
        other=con.execute("SELECT id FROM users WHERE username='Other'").fetchone()[0]
        con.execute("INSERT INTO households(id,name,created_at) VALUES(2,'另家','now')")
        con.execute("UPDATE users SET household_id=2 WHERE id=?",(other,))
        con.execute("INSERT INTO users(username,password_hash,created_at) VALUES('Base','x','now')")
        base=con.execute("SELECT id FROM users WHERE username='Base'").fetchone()[0]
        con.commit()
        assert base in member_ids(con,base)
        assert other not in member_ids(con,base)
        clause,params=book_visibility_sql(con,base)
        assert 'owner_id IN' in clause and params
