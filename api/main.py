import sqlite3
import os
import zlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from typing_extensions import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))
DB_PATH = DATA_DIR / "app.db"
# Comma list of allowed browser origins. Empty = open (local dev).
ALLOWED_ORIGINS = [o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o]

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.middleware("http")
async def origin_lock(request: Request, call_next):
    # ponytail: Origin is spoofable by non-browser clients; add a proxy secret header if abuse appears.
    origin = request.headers.get("origin")
    if ALLOWED_ORIGINS and origin and origin not in ALLOWED_ORIGINS:
        return JSONResponse({"detail": "forbidden origin"}, status_code=403)
    return await call_next(request)


@app.get("/health")
def health():
    return {"ok": True}


def query(sql, params=()):
    if not DB_PATH.exists():
        return []
    try:
        with sqlite3.connect(DB_PATH) as db:
            db.row_factory = sqlite3.Row
            return db.execute(sql, params).fetchall()
    except sqlite3.OperationalError as err:
        if "no such table" not in str(err):
            raise
        return []  # tables not created yet, ingest has not run


def page(rows, limit, after):
    has_more = len(rows) > limit
    return {
        "data": rows[:limit],
        "nextCursor": after + limit if has_more else None,
        "hasMore": has_more,
    }


@app.get("/api/v1/videos")
@app.get("/get-videos")
def get_videos(
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    after: Annotated[int, Query(ge=0)] = 0,
):
    rows = query("""
        SELECT v.video_id, v.channel_id, v.published_at, v.view_count
        FROM videos v
        JOIN subscriptions s ON s.channel_id = v.channel_id
        WHERE v.is_short = 1
    """)
    # ponytail: ranks every short per request, cache by (day, row count) if the table gets big.
    # Seeded by UTC day so offset paging is stable within a day; a mid-day ingest can shift pages once.
    now = datetime.now(timezone.utc)
    ranked = rank_feed(rows, now, now.date().isoformat())
    return page(ranked[after:after + limit + 1], limit, after)


HALF_LIFE_DAYS = 7  # a week-old short scores half of a new one


def rank_feed(rows, now, seed):
    """Order video ids by freshness * hotness * daily jitter, never the same channel twice in a row."""
    views_by_channel = defaultdict(list)
    for r in rows:
        if r["view_count"] is not None:
            views_by_channel[r["channel_id"]].append(r["view_count"])
    avg_views = {c: sum(v) / len(v) for c, v in views_by_channel.items()}

    def score(r):
        published = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - published).total_seconds() / 86400)
        freshness = 0.5 ** (age_days / HALF_LIFE_DAYS)
        hotness = 1.0
        if r["view_count"] is not None:  # beating its own channel's average = hot
            hotness = min(2.0, max(0.5, ((r["view_count"] + 1) / (avg_views[r["channel_id"]] + 1)) ** 0.3))
        # crc32, not hash(): hash() is salted per process, so workers would disagree on the order
        jitter = 0.5 + zlib.crc32(f"{seed}:{r['video_id']}".encode()) / 2**32
        return freshness * hotness * jitter

    out, held = [], []  # held: items waiting because their channel just played
    for r in sorted(rows, key=score, reverse=True):
        held.append(r)
        while held:
            i = next((k for k, h in enumerate(held) if not out or h["channel_id"] != out[-1]["channel_id"]), None)
            if i is None:
                break
            out.append(held.pop(i))
    out += held  # only one channel left, nothing to interleave with
    return [r["video_id"] for r in out]


@app.get("/api/v1/channels")
def get_channels():
    rows = query("""
        SELECT s.channel_id, s.title, s.thumbnail, COUNT(v.video_id) AS video_count
        FROM subscriptions s
        LEFT JOIN videos v ON v.channel_id = s.channel_id
        GROUP BY s.channel_id
        ORDER BY s.title COLLATE NOCASE
    """)
    return [dict(row) for row in rows]


@app.get("/api/v1/library")
def get_library(
    channel_id: Optional[str] = None,
    kind: Literal["all", "short", "long"] = "all",
    sort: Literal["recent", "oldest", "views"] = "recent",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    after: Annotated[int, Query(ge=0)] = 0,
):
    rows = query("""
        SELECT v.video_id, v.channel_id, s.title AS channel_title, v.title,
               v.published_at, v.duration_seconds, v.is_short, v.view_count, v.youtube_url AS url
        FROM videos v
        JOIN subscriptions s ON s.channel_id = v.channel_id
        WHERE (:channel_id IS NULL OR :channel_id = '' OR v.channel_id = :channel_id)
          AND (:kind = 'all' OR v.is_short = (:kind = 'short'))
        ORDER BY
            CASE :sort WHEN 'views' THEN v.view_count END DESC,
            CASE :sort WHEN 'oldest' THEN v.published_at END ASC,
            v.published_at DESC, v.video_id
        LIMIT :limit OFFSET :after
    """, {"sort": sort, "channel_id": channel_id, "kind": kind, "limit": limit + 1, "after": after})
    videos = [
        {
            **dict(row),
            "is_short": bool(row["is_short"]),
            "thumbnail": f"https://i.ytimg.com/vi/{row['video_id']}/hqdefault.jpg",
        }
        for row in rows
    ]
    return page(videos, limit, after)
