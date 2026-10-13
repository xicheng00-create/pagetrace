import io
import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import create_app
from data.db import get_db
from services.upload import extract_text, validate_pdf


def pdf_bytes(pages=2, text=True):
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(40, 40, 550, 750),
                                ('Knowledge supports deliberate practice and useful feedback.\n' * 8))
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'db.sqlite3'))
    app = create_app('development')
    from data.models import migrate, migrate_upload
    with app.app_context():
        migrate_upload(get_db())
        get_db().commit()
    app.config.update(TESTING=True, UPLOAD_ROOT=str(tmp_path / 'uploads'))
    return app.test_client()


def submit(client, data, filename='book.pdf'):
    return client.post('/api/upload', data={'file': (io.BytesIO(data), filename)})


def test_reject_nontext_pdf(client):
    response = submit(client, pdf_bytes(text=False))
    assert response.json['code'] != 0 and '扫描件' in response.json['msg']
    with client.application.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM upload_jobs').fetchone()[0] == 0
    assert not Path(client.application.config['UPLOAD_ROOT']).exists()


def test_reject_oversize_and_page_limit(client, monkeypatch):
    from services import upload
    monkeypatch.setattr(upload, 'MAX_BYTES', 100)
    assert '50 MB' in submit(client, pdf_bytes()).json['msg']
    monkeypatch.setattr(upload, 'MAX_BYTES', 50 * 1024 * 1024)
    assert '600' in submit(client, pdf_bytes(601)).json['msg']
    assert not Path(client.application.config['UPLOAD_ROOT']).exists()


def test_upload_accepts_only_valid_pdf(client):
    assert client.post('/api/upload').status_code == 400
    assert submit(client, b'fake', 'x.txt').status_code == 400
    assert submit(client, b'%PDF-broken').status_code == 400
    response = submit(client, pdf_bytes())
    assert response.status_code == 202
    assert response.json['data']['pages'] == 2
    assert len(list(Path(client.application.config['UPLOAD_ROOT']).rglob('*.pdf'))) == 1
    assert submit(client, pdf_bytes()).status_code == 202
    with client.application.app_context():
        from services.upload import find_pooled_book
        assert find_pooled_book(get_db(), response.json['data']['book_hash']) is None


def test_extract_idempotent_by_sha256(tmp_path):
    path = tmp_path / 'book.pdf'
    path.write_bytes(pdf_bytes())
    first = extract_text(path, tmp_path)
    mtime = Path(first['path']).stat().st_mtime_ns
    second = extract_text(path, tmp_path)
    assert second['cached'] and not first['cached']
    assert Path(first['path']).stat().st_mtime_ns == mtime


def test_extract_keeps_page_markers(tmp_path):
    path = tmp_path / 'book.pdf'
    path.write_bytes(pdf_bytes(3))
    text = Path(extract_text(path, tmp_path)['path']).read_text()
    assert '<!-- p.1 -->' in text and text.count('<!-- p.') == 3


def test_encrypted_and_empty_rejected():
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='user')
    with pytest.raises(ValueError, match='加密'):
        validate_pdf(data, 'book.pdf')


def test_extract_cli(tmp_path, monkeypatch, capsys):
    from scripts.extract_text import main
    path = tmp_path / 'fixture.pdf'
    path.write_bytes(pdf_bytes())
    monkeypatch.setattr(sys, 'argv', ['extract_text', str(path), '--root', str(tmp_path)])
    main()
    assert 'cached' in capsys.readouterr().out


def test_db_failure_removes_only_new_pdf(tmp_path):
    import sqlite3
    from data.models import migrate, migrate_upload
    from data.s2_schema import fresh_schema
    from services.upload import accept_upload
    con = sqlite3.connect(':memory:')
    con.executescript(fresh_schema())
    con.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES('owner','test','owner','t')")
    migrate(con)
    migrate_upload(con)
    con.execute("CREATE TRIGGER fail_job BEFORE INSERT ON upload_jobs BEGIN SELECT RAISE(ABORT,'probe'); END")
    con.commit()
    root = tmp_path / 'uploads'
    data = pdf_bytes()
    with pytest.raises(sqlite3.IntegrityError):
        accept_upload(con, data, 'book.pdf', root)
    assert not list(root.rglob('*.pdf'))
    target = root / 'in' / (validate_pdf(data, 'book.pdf')['book_hash'] + '.pdf')
    target.write_bytes(data)
    with pytest.raises(sqlite3.IntegrityError):
        accept_upload(con, data, 'book.pdf', root)
    assert target.read_bytes() == data
