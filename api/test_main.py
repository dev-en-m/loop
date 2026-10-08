"""Run: python api/test_main.py (needs docker/requirements.txt installed)."""
import asyncio
import sqlite3
import tempfile
import time
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
        db.execute("CREATE TABLE videos (video_id TEXT, channel_id TEXT, published_at TEXT, is_short INTEGER, view_count INTEGER)")
        db.execute("INSERT INTO subscriptions VALUES ('sub')")
        db.executemany("INSERT INTO videos VALUES (?,?,?,?,?)", [
            ("s1", "sub", "2026-01-01", 1, None),
            ("s2", "sub", "2026-01-02T10:00:00Z", 1, 5),
            ("long", "sub", "2026-01-03", 0, 5),      # not a short
            ("other", "nosub", "2026-01-04", 1, 5),   # not subscribed
            ("t2", "sub", "2026-01-02", 1, 5),
        ])
        db.commit()
        full = main.get_videos()["data"]
        assert sorted(full) == ["s1", "s2", "t2"]
        page = main.get_videos(limit=1)
        assert page["data"] == full[:1] and page["hasMore"] and page["nextCursor"] == 1
        # no repeat or skip across pages
        assert [main.get_videos(limit=1, after=i)["data"][0] for i in range(3)] == full
        assert main.get_videos(limit=1, after=2)["hasMore"] is False

        # an old-schema db must fail loudly, not look like an empty feed
        db.execute("ALTER TABLE videos RENAME COLUMN is_short TO is_short_old")
        db.commit()
        try:
            main.get_videos()
            assert False, "expected OperationalError"
        except sqlite3.OperationalError:
            pass


def test_rank_feed():
    from datetime import datetime, timezone
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    row = lambda i, c, d, v=None: {"video_id": i, "channel_id": c, "published_at": d, "view_count": v}
    rows = [
        row("a_new", "a", "2026-01-31T12:00:00Z"),
        row("a_new2", "a", "2026-01-31T11:00:00Z"),
        row("a_new3", "a", "2026-01-31T10:00:00Z"),
        row("b_old", "b", "2025-12-01T00:00:00Z"),
        row("c_old", "c", "2025-12-02T00:00:00Z"),
    ]
    ranked = main.rank_feed(rows, now, "2026-02-01")
    assert sorted(ranked) == sorted(r["video_id"] for r in rows)
    assert ranked[0].startswith("a_new")  # 2 months old can't beat 1 day old, even with jitter
    channels = [i[0] for i in ranked]
    assert all(x != y for x, y in zip(channels, channels[1:])), channels  # a's run is split by b and c
    assert ranked == main.rank_feed(rows, now, "2026-02-01")  # same day, same order

    # jitter reshuffles videos of similar age from day to day
    same_age = [row(f"v{n}", f"ch{n}", "2026-01-31T00:00:00Z") for n in range(20)]
    assert main.rank_feed(same_age, now, "day1") != main.rank_feed(same_age, now, "day2")

    # a short far above its channel's average outranks a same-age dud
    hot = [row("hot", "a", "2026-01-31", 100_000), row("dud", "b", "2026-01-31", 10)] + \
          [row(f"a{n}", "a", "2026-01-31", 100) for n in range(5)] + [row("b1", "b", "2026-01-31", 100_000)]
    ranked = main.rank_feed(hot, now, "s")
    assert ranked.index("hot") < ranked.index("dud")

    # watch history: seen goes last, finished channels rise, skipped channels sink
    many = [row(f"{c}{n}", c, "2026-01-31") for c in "lsn" for n in range(30)]
    view = lambda i, c, ratio: {"video_id": i, "channel_id": c, "watch_ratio": ratio}
    views = [view(f"l{n}", "l", 1.0) for n in range(5)] + [view(f"s{n}", "s", 0.0) for n in range(5)]
    mean_pos = lambda ranked, c: sum(i for i, v in enumerate(ranked) if v[0] == c and v not in seen) / 25
    seen = {f"{c}{n}" for c in "ls" for n in range(5)}
    for seed in ["a", "b", "c"]:
        ranked = main.rank_feed(many, now, seed, views)
        # seen land at the tail (interleave may slot leftover unseen of one channel between them)
        assert min(ranked.index(v) for v in seen) >= len(ranked) - 20, ranked[-20:]
        assert mean_pos(ranked, "l") < mean_pos(ranked, "n") < mean_pos(ranked, "s"), seed
    ranked = main.rank_feed(many, now, "a", views)
    assert any(v[0] == "s" for v in ranked[:45])  # skipped channel sinks but is not buried at the end


def test_events():
    with tempfile.TemporaryDirectory() as d:
        main.DB_PATH = Path(d) / "app.db"
        main.post_event("abcdefghijk", 0.5)  # no db yet: no-op, does not create one
        assert not main.DB_PATH.exists()

        db = sqlite3.connect(main.DB_PATH)
        db.close()
        main.post_event("abcdefghijk", 0.5)  # videos table missing: no-op

        db = sqlite3.connect(main.DB_PATH)
        db.execute("CREATE TABLE subscriptions (channel_id TEXT PRIMARY KEY)")
        db.execute("CREATE TABLE videos (video_id TEXT, channel_id TEXT, published_at TEXT, is_short INTEGER, view_count INTEGER)")
        db.execute("INSERT INTO subscriptions VALUES ('a'), ('b')")
        db.executemany("INSERT INTO videos VALUES (?,?,?,1,NULL)",
                       [(f"a{n:010d}", "a", "2026-01-01") for n in range(5)] + [(f"b{n:010d}", "b", "2026-01-01") for n in range(5)])
        db.commit()
        before = main.get_videos(session=1)["data"]
        assert main.get_videos(session=1) == main.get_videos(session=1)

        main.post_event("a0000000000", 1.0)
        main.post_event("zzzzzzzzzzz", 1.0)  # unknown id: dropped
        assert db.execute("SELECT video_id, watch_ratio FROM views").fetchall() == [("a0000000000", 1.0)]

        # events after the session started do not move pages of that session
        assert main.get_videos(session=1)["data"] == before
        # next session sees it: the watched short goes to the tail (4 a + 5 b unseen, so it splits the last b pair)
        assert "a0000000000" in main.get_videos(session=int(time.time() * 1000) + 1000)["data"][-2:]


def asgi_status(method, path, query=b"", headers=()):
    scope = {"type": "http", "method": method, "path": path, "query_string": query,
             "headers": list(headers), "http_version": "1.1", "scheme": "http", "server": ("t", 80)}
    out = []

    async def send(msg):
        out.append(msg)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    asyncio.run(main.app(scope, receive, send))
    return out[0]["status"]


def test_event_validation():
    with tempfile.TemporaryDirectory() as d:
        main.DB_PATH = Path(d) / "app.db"
        assert asgi_status("POST", "/api/v1/events", b"video_id=bad&watch_ratio=0.5") == 422
        assert asgi_status("POST", "/api/v1/events", b"video_id=abcdefghijk&watch_ratio=2") == 422
        assert asgi_status("POST", "/api/v1/events", b"video_id=abcdefghijk&watch_ratio=0.5") == 204


def test_channels_and_library():
    with tempfile.TemporaryDirectory() as d:
        main.DB_PATH = Path(d) / "app.db"
        assert main.get_channels() == [] and main.get_library()["data"] == []  # no db

        db = sqlite3.connect(main.DB_PATH)
        db.execute("CREATE TABLE subscriptions (channel_id TEXT PRIMARY KEY, title TEXT, thumbnail TEXT, synced_at TEXT)")
        db.execute("CREATE TABLE videos (video_id TEXT, channel_id TEXT, title TEXT, published_at TEXT, duration_seconds INTEGER, is_short INTEGER, youtube_url TEXT, view_count INTEGER)")
        db.executemany("INSERT INTO subscriptions VALUES (?,?,?,'')", [("a", "Alpha", "ta"), ("b", "beta", "tb"), ("c", "Empty", "tc")])
        db.executemany("INSERT INTO videos VALUES (?,?,?,?,?,?,?,?)", [
            (i, c, t, d, n, s, f"https://www.youtube.com/watch?v={i}", w)
            for i, c, t, d, n, s, w in [
                ("a1", "a", "A one", "2026-01-01", 30, 1, 50),
                ("a2", "a", "A two", "2026-01-03", 600, 0, None),
                ("b1", "b", "B one", "2026-01-02", 20, 1, 900),
                ("x1", "nosub", "X", "2026-01-04", 20, 1, 5),  # not subscribed
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
        assert ids(sort="oldest") == ["a1", "b1", "a2"]
        assert ids(sort="views") == ["b1", "a1", "a2"]  # NULL counts last
        first = main.get_library(limit=2)
        assert first["hasMore"] and first["nextCursor"] == 2 and ids(limit=2, after=2) == ["a1"]
        v = first["data"][0]
        assert v["is_short"] is False and v["channel_title"] == "Alpha"
        assert v["thumbnail"].endswith("/a2/hqdefault.jpg") and v["url"].endswith("v=a2")


def test_origin_lock():
    def status(origin):
        return asgi_status("GET", "/health", headers=[(b"origin", origin.encode())] if origin else [])

    main.ALLOWED_ORIGINS[:] = ["https://loop.devendram.com"]
    try:
        assert status("https://loop.devendram.com") == 200
        assert status("https://evil.example") == 403
        assert status(None) == 200  # curl, uptime checks
    finally:
        main.ALLOWED_ORIGINS.clear()
    assert status("https://evil.example") == 200  # unset = open (local dev)


if __name__ == "__main__":
    test_feed_only_subscribed_shorts()
    test_rank_feed()
    test_events()
    test_event_validation()
    test_channels_and_library()
    test_origin_lock()
    print("ok")
