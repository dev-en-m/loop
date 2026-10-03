"""Run: python api/test_main.py (needs docker/requirements.txt installed)."""
import sqlite3
import tempfile
from pathlib import Path

import main


def test_feed_only_subscribed_shorts():
    with tempfile.TemporaryDirectory() as d:
        main.DB_PATH = Path(d) / "app.db"
        assert main.get_videos()["data"] == []  # empty db file absent

        db = sqlite3.connect(main.DB_PATH)
        db.close()
        assert main.get_videos()["data"] == []  # tables missing

        db = sqlite3.connect(main.DB_PATH)
        db.execute("CREATE TABLE subscriptions (channel_id TEXT PRIMARY KEY)")
        db.execute("CREATE TABLE videos (video_id TEXT, channel_id TEXT, published_at TEXT, is_short INTEGER)")
        db.execute("INSERT INTO subscriptions VALUES ('sub')")
        db.executemany("INSERT INTO videos VALUES (?,?,?,?)", [
            ("s1", "sub", "2026-01-01", 1),
            ("s2", "sub", "2026-01-02", 1),
            ("long", "sub", "2026-01-03", 0),      # not a short
            ("other", "nosub", "2026-01-04", 1),   # not subscribed
        ])
        db.commit()
        assert main.get_videos()["data"] == ["s2", "s1"]
        page = main.get_videos(limit=1)
        assert page["data"] == ["s2"] and page["hasMore"] and page["nextCursor"] == 1


if __name__ == "__main__":
    test_feed_only_subscribed_shorts()
    print("ok")
