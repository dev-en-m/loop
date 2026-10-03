import sqlite3
import os
from pathlib import Path
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


@app.get("/api/v1/videos")
@app.get("/get-videos")
def get_videos(
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    after: Annotated[int, Query(ge=0)] = 0,
):
    if not DB_PATH.exists():
        return {"data": [], "nextCursor": None, "hasMore": False}

    try:
        with sqlite3.connect(DB_PATH) as db:
            rows = db.execute("""
                SELECT v.video_id
                FROM videos v
                JOIN subscriptions s ON s.channel_id = v.channel_id
                WHERE v.is_short = 1
                ORDER BY v.published_at DESC, v.video_id
                LIMIT ? OFFSET ?
            """, (limit + 1, after)).fetchall()
    except sqlite3.OperationalError as err:
        if "no such table" not in str(err):
            raise
        rows = []  # tables not created yet, ingest has not run

    ids = [row[0] for row in rows[:limit]]
    has_more = len(rows) > limit
    return {
        "data": ids,
        "nextCursor": after + limit if has_more else None,
        "hasMore": has_more,
    }
