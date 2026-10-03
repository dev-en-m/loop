import sqlite3
import os
from pathlib import Path
from typing import Literal, Optional
from typing_extensions import Annotated

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))
DB_PATH = DATA_DIR / "app.db"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


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
        SELECT v.video_id
        FROM videos v
        JOIN subscriptions s ON s.channel_id = v.channel_id
        WHERE v.is_short = 1
        ORDER BY v.published_at DESC, v.video_id
        LIMIT ? OFFSET ?
    """, (limit + 1, after))
    return page([row[0] for row in rows], limit, after)


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
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    after: Annotated[int, Query(ge=0)] = 0,
):
    rows = query("""
        SELECT v.video_id, v.channel_id, s.title AS channel_title, v.title,
               v.published_at, v.duration_seconds, v.is_short
        FROM videos v
        JOIN subscriptions s ON s.channel_id = v.channel_id
        WHERE (:channel_id IS NULL OR v.channel_id = :channel_id)
          AND (:kind = 'all' OR v.is_short = (:kind = 'short'))
        ORDER BY v.published_at DESC, v.video_id
        LIMIT :limit OFFSET :after
    """, {"channel_id": channel_id, "kind": kind, "limit": limit + 1, "after": after})
    videos = [
        {
            **dict(row),
            "is_short": bool(row["is_short"]),
            "thumbnail": f"https://i.ytimg.com/vi/{row['video_id']}/hqdefault.jpg",
            "url": f"https://www.youtube.com/watch?v={row['video_id']}",
        }
        for row in rows
    ]
    return page(videos, limit, after)
