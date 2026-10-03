"""Run: python api/test_ingest.py (needs docker/requirements.txt installed)."""
import sqlite3
import tempfile
from pathlib import Path

import ingest_youtube_shorts as m


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
            {"id": i, "snippet": {"channelId": "UCabc", "title": i, "publishedAt": "x"},
             "contentDetails": {"duration": "PT45S" if i == "v0" else "PT10M"}}
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
        # cutoff 2026-01-21: v0..v9 are on/after it (days 30..21), older ones stop the paging
        found, shorts = m.ingest_channel(db, "k", {"channel_id": "UCabc", "handle": "h"},
                                         {"UCabc": "2026-01-21T00:00:00Z"}, now)
        assert (found, shorts) == (10, 1), (found, shorts)
        assert db.execute("select count(*) from videos").fetchone()[0] == 10
        assert db.execute("select is_short from videos where video_id='v0'").fetchone() == (1,)
        assert db.execute("select is_short from videos where video_id='v1'").fetchone() == (0,)
        assert m.STATE_FILE.exists()


def test_fetch_details_batches():
    calls = []
    m.requests.get = fake_get_factory(calls)
    out = m.fetch_video_details("k", [f"v{i}" for i in range(120)])
    assert len(out) == 120 and len(calls) == 3


if __name__ == "__main__":
    test_ingest_channel()
    test_fetch_details_batches()
    print("ok")
