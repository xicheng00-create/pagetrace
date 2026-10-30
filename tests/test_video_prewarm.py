def test_daily_run_table_exists(video_client):
    with video_client.application.app_context():
        from data.db import get_db

        assert (
            get_db().execute("SELECT name FROM sqlite_master WHERE name='card_video_daily_runs'").fetchone()
        )
