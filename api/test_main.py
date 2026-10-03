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
            ("t2", "sub", "2026-01-02", 1),        # same published_at as s2: tiebreak by video_id
        ])
        db.commit()
        assert main.get_videos()["data"] == ["s2", "t2", "s1"]
        page = main.get_videos(limit=1)
        assert page["data"] == ["s2"] and page["hasMore"] and page["nextCursor"] == 1
        assert main.get_videos(limit=1, after=1)["data"] == ["t2"]  # no repeat or skip across pages

        # an old-schema db must fail loudly, not look like an empty feed
        db.execute("ALTER TABLE videos RENAME COLUMN is_short TO is_short_old")
        db.commit()
        try:
            main.get_videos()
            assert False, "expected OperationalError"
        except sqlite3.OperationalError:
            pass


def test_channels_and_library():
    with tempfile.TemporaryDirectory() as d:
        main.DB_PATH = Path(d) / "app.db"
        assert main.get_channels() == [] and main.get_library()["data"] == []  # no db

        db = sqlite3.connect(main.DB_PATH)
        db.execute("CREATE TABLE subscriptions (channel_id TEXT PRIMARY KEY, title TEXT, thumbnail TEXT, synced_at TEXT)")
        db.execute("CREATE TABLE videos (video_id TEXT, channel_id TEXT, title TEXT, published_at TEXT, duration_seconds INTEGER, is_short INTEGER, youtube_url TEXT)")
        db.executemany("INSERT INTO subscriptions VALUES (?,?,?,'')", [("a", "Alpha", "ta"), ("b", "beta", "tb"), ("c", "Empty", "tc")])
        db.executemany("INSERT INTO videos VALUES (?,?,?,?,?,?,?)", [
            (i, c, t, d, n, s, f"https://www.youtube.com/watch?v={i}")
            for i, c, t, d, n, s in [
                ("a1", "a", "A one", "2026-01-01", 30, 1),
                ("a2", "a", "A two", "2026-01-03", 600, 0),
                ("b1", "b", "B one", "2026-01-02", 20, 1),
                ("x1", "nosub", "X", "2026-01-04", 20, 1),  # not subscribed
            ]
        ])
        db.commit()

        channels = main.get_channels()
        assert [(c["title"], c["video_count"]) for c in channels] == [("Alpha", 2), ("beta", 1), ("Empty", 0)]

        ids = lambda **kw: [v["video_id"] for v in main.get_library(**kw)["data"]]
        assert ids() == ["a2", "b1", "a1"]
        assert ids(channel_id="") == ["a2", "b1", "a1"]  # empty param (UI "All") means no filter
        assert ids(channel_id="a") == ["a2", "a1"]
        assert ids(kind="short") == ["b1", "a1"]
        assert ids(kind="long") == ["a2"]
        assert ids(channel_id="a", kind="short") == ["a1"]
        assert ids(channel_id="zzz") == []
        first = main.get_library(limit=2)
        assert first["hasMore"] and first["nextCursor"] == 2 and ids(limit=2, after=2) == ["a1"]
        v = first["data"][0]
        assert v["is_short"] is False and v["channel_title"] == "Alpha"
        assert v["thumbnail"].endswith("/a2/hqdefault.jpg") and v["url"].endswith("v=a2")


if __name__ == "__main__":
    test_feed_only_subscribed_shorts()
    test_channels_and_library()
    print("ok")
