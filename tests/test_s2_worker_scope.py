"""后台多租户调度保留全局 FIFO，任务必须按 owner 读取并传递身份。"""
from app import create_app
from data.db import get_db
from services import worker


def test_worker_selects_each_owner_and_preserves_global_fifo(monkeypatch):
    app = create_app('development')
    with app.app_context():
        con = get_db()
        for uid in (1, 2):
            con.execute("INSERT INTO users (id, username, password_hash, role, created_at) VALUES(?,?,?,'member','t')", (uid, str(uid), 'unused'))
        for job_id, owner in ((1, 2), (2, 1), (3, 2)):
            con.execute(
                "INSERT INTO upload_jobs(id,book_hash,filename,pages,status,stage,created_at,updated_at,owner_id) "
                "VALUES(?,?,'fixture.pdf',1,'queued','queued','t','t',?)", (job_id, str(job_id), owner))
        con.commit()
    seen = []

    def complete(con, job_id, root, user_id):
        seen.append((job_id, user_id))
        assert con.execute('SELECT owner_id FROM upload_jobs WHERE id=? AND owner_id=?',
                           (job_id, user_id)).fetchone() is not None
        con.execute("UPDATE upload_jobs SET status='ready' WHERE id=? AND owner_id=?", (job_id, user_id))
        con.commit()

    monkeypatch.setattr(worker, 'run_job', complete)
    worker.drain(app)
    assert seen == [(1, 2), (2, 1), (3, 2)]
