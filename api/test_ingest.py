"""Run: python api/test_ingest.py (needs docker/requirements.txt installed)."""
import sqlite3
import tempfile
from pathlib import Path

import ingest_youtube_shorts as m


DURATIONS = {"v0": "PT45S", "v3": "P1DT2H", "v4": "P0D"}


class Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def fake_get_factory(calls):
    # 120 uploads, newest first, one per day; ids v0 (newest) .. v119
    def fake_get(url, params, **_):
        calls.append((url, dict(params)))
        if url == m.GOOGLE_YT_PLAYLIST_ITEMS_URL:
            assert params["playlistId"] == "UUabc"
            start = int(params.get("pageToken", 0))
            items = [
                {"contentDetails": {"videoId": f"v{i}", "videoPublishedAt": f"2026-01-{30 - i:02d}T00:00:00Z"}}
                for i in range(start, min(start + 50, 30))
            ]
            items.append({"contentDetails": {"videoId": "private"}})  # no date
            nxt = {"nextPageToken": str(start + 50)} if start + 50 < 30 else {}
            return Resp({"items": items, **nxt})
        ids = params["id"].split(",")
        assert len(ids) <= 50
        return Resp({"items": [
            {"id": i, "snippet": {"channelId": "UCabc", "title": i, "publishedAt": "x",
                                  "liveBroadcastContent": "live" if i == "v2" else "none"},
             "contentDetails": {"duration": DURATIONS.get(i, "PT10M")}}
            for i in ids
        ]})
    return fake_get


def test_ingest_channel():
    calls = []
    m.requests.get = fake_get_factory(calls)
    with tempfile.TemporaryDirectory() as d:
        m.STATE_FILE = Path(d) / "state.json"
        db = sqlite3.connect(":memory:")
        db.execute("""CREATE TABLE videos (video_id TEXT PRIMARY KEY, channel_id TEXT, title TEXT,
            published_at TEXT, duration_seconds INTEGER, is_short INTEGER, youtube_url TEXT)""")
        db.execute("CREATE TABLE channel_activity (channel_id TEXT PRIMARY KEY, handle TEXT, last_run_at TEXT)")
        from datetime import datetime, timezone
        now = datetime(2026, 1, 31, tzinfo=timezone.utc)
        # last run 2026-01-22 minus 1 day overlap = cutoff 01-21: v0..v9 on/after (days 30..21);
        # v10..v19 are old, 10 in a row stops paging
        state = {"UCabc": "2026-01-22T00:00:00Z"}
        found, new = m.ingest_channel(db, "k", {"channel_id": "UCabc", "handle": "h"}, state, now)
        assert (found, new) == (10, 9), (found, new)  # v2 is live, skipped
        assert db.execute("select is_short from videos where video_id='v0'").fetchone() == (1,)
        assert db.execute("select is_short from videos where video_id='v1'").fetchone() == (0,)
        assert db.execute("select video_id from videos where video_id='v2'").fetchone() is None
        # unparseable durations are not Shorts, never 1
        assert db.execute("select is_short from videos where video_id in ('v3','v4')").fetchall() == [(0,), (0,)]
        # rerun inserts nothing new
        state["UCabc"] = "2026-01-22T00:00:00Z"
        assert m.ingest_channel(db, "k", {"channel_id": "UCabc", "handle": "h"}, state, now)[1] == 0
        assert m.STATE_FILE.exists()


def test_fetch_details_batches():
    calls = []
    m.requests.get = fake_get_factory(calls)
    out = m.fetch_video_details("k", [f"v{i}" for i in range(120)])
    assert len(out) == 119 and len(calls) == 3  # v2 is live


def test_blocked_channels():
    with tempfile.TemporaryDirectory() as d:
        m.BLOCKED_FILE = Path(d) / "blocked.txt"
        m.BLOCKED_FILE.write_text("# header\nUCbad  # News\n\n")
        m.fetch_subscriptions = lambda: [("UCgood", "Good", ""), ("UCbad", "News", "")]
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE videos (video_id TEXT, channel_id TEXT)")
        db.execute("CREATE TABLE channel_activity (channel_id TEXT)")
        db.execute("""CREATE TABLE subscriptions (channel_id TEXT PRIMARY KEY, title TEXT,
            thumbnail TEXT, synced_at TEXT)""")
        db.executemany("INSERT INTO videos VALUES (?, ?)", [("a", "UCbad"), ("b", "UCgood")])
        db.execute("INSERT INTO channel_activity VALUES ('UCbad')")
        db.execute("INSERT INTO subscriptions VALUES ('UCbad', 'News', '', 'old')")
        assert m.sync_subscriptions(db, "now") == 1
        assert db.execute("select channel_id from subscriptions").fetchall() == [("UCgood",)]
        assert db.execute("select video_id from videos").fetchall() == [("b",)]
        assert db.execute("select count(*) from channel_activity").fetchone() == (0,)


if __name__ == "__main__":
    test_blocked_channels()
    test_ingest_channel()
    test_fetch_details_batches()
    print("ok")
