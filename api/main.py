import sqlite3
import os
import zlib
from collections import defaultdict
from datetime import datetime, time, timezone
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
    allow_methods=["GET", "POST"],
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
    session: Annotated[Optional[int], Query(ge=0)] = None,  # client's page-load time, epoch ms
):
    rows = query("""
        SELECT v.video_id, v.channel_id, v.published_at, v.view_count
        FROM videos v
        JOIN subscriptions s ON s.channel_id = v.channel_id
        WHERE v.is_short = 1
    """)
    # ponytail: ranks every short per request, cache by (day, row count) if the table gets big.
    # Order is a pure function of the seed and of watch events before the cutoff, so offset paging
    # stays stable within a session (or a UTC day without one); a mid-day ingest can shift pages once.
    # Client clock skew of a few seconds can let early events of this session leak in; harmless.
    now = datetime.now(timezone.utc)
    if session is None:
        seed, cutoff = now.date().isoformat(), datetime.combine(now.date(), time(), timezone.utc)
    else:
        seed, cutoff = str(session), datetime.fromtimestamp(session / 1000, timezone.utc)
    views = query("""
        SELECT w.video_id, v.channel_id, w.watch_ratio
        FROM views w JOIN videos v ON v.video_id = w.video_id
        WHERE w.seen_at < ?
    """, (cutoff.isoformat(timespec="milliseconds"),))
    ranked = rank_feed(rows, now, seed, views)
    return page(ranked[after:after + limit + 1], limit, after)


@app.post("/api/v1/events", status_code=204)
def post_event(
    video_id: Annotated[str, Query(pattern=r"^[A-Za-z0-9_-]{11}$")],
    watch_ratio: Annotated[float, Query(ge=0, le=1)],
):
    # Query params, not a JSON body: keeps the browser POST a CORS "simple" request (no preflight).
    if not DB_PATH.exists():
        return
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS views (
                video_id TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                watch_ratio REAL NOT NULL
            )
        """)
        try:
            db.execute("""
                INSERT INTO views SELECT ?, ?, ? WHERE EXISTS (SELECT 1 FROM videos WHERE video_id = ?)
            """, (video_id, datetime.now(timezone.utc).isoformat(timespec="milliseconds"), watch_ratio, video_id))
        except sqlite3.OperationalError as err:
            if "no such table" not in str(err):
                raise  # videos missing: ingest has not run, nothing to record


HALF_LIFE_DAYS = 7  # a week-old short scores half of a new one
AFFINITY_PRIOR = 3  # a channel needs a few events before watch history moves it far from neutral


def rank_feed(rows, now, seed, views=()):
    """Order video ids: unseen before seen, then by freshness * hotness * channel affinity * jitter,
    never the same channel twice in a row. views = (video_id, channel_id, watch_ratio) events."""
    seen = {w["video_id"] for w in views}
    ratios = defaultdict(list)
    for w in views:
        ratios[w["channel_id"]].append(w["watch_ratio"])
    # 0.5 (always skipped) .. 1.5 (always finished), 1.0 with no history. Floor 0.5 + jitter keep
    # skipped channels showing up now and then, so they can win back.
    affinity = {c: 0.5 + (sum(r) + 0.5 * AFFINITY_PRIOR) / (len(r) + AFFINITY_PRIOR) for c, r in ratios.items()}

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
        return freshness * hotness * affinity.get(r["channel_id"], 1.0) * jitter

    out, held = [], []  # held: items waiting because their channel just played
    for r in sorted(rows, key=lambda r: (r["video_id"] not in seen, score(r)), reverse=True):
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
