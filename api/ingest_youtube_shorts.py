import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))

DB_PATH = DATA_DIR / "app.db"
STATE_FILE = DATA_DIR / "last_run_by_channel.json"
BLOCKED_FILE = BASE_DIR / "blocked_channels.txt"
TOKEN_FILE = DATA_DIR / "token.json"

GOOGLE_YT_PLAYLIST_ITEMS_URL = os.environ.get(
    "GOOGLE_YT_PLAYLIST_ITEMS_URL",
    "https://www.googleapis.com/youtube/v3/playlistItems",
)
GOOGLE_YT_SUBS_URL = os.environ.get(
    "GOOGLE_YT_SUBS_URL",
    "https://www.googleapis.com/youtube/v3/subscriptions",
)
GOOGLE_YT_VIDEOS_URL = os.environ.get(
    "GOOGLE_YT_VIDEOS_URL",
    "https://www.googleapis.com/youtube/v3/videos",
)


def fetch_subscriptions():
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(f"{TOKEN_FILE} missing, run api/auth_youtube.py first")
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE))
    creds.refresh(Request())

    subs, page_token = [], None
    while True:
        params = {"part": "snippet", "mine": "true", "maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        response = requests.get(
            GOOGLE_YT_SUBS_URL,
            params=params,
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        for item in data.get("items", []):
            snippet = item["snippet"]
            subs.append((
                snippet["resourceId"]["channelId"],
                snippet.get("title", ""),
                snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
            ))
        page_token = data.get("nextPageToken")
        if not page_token:
            return subs


def load_blocked():
    lines = (line.split("#")[0].strip() for line in BLOCKED_FILE.read_text().splitlines())
    return {line for line in lines if line}


def sync_subscriptions(db, synced_at):
    subs = fetch_subscriptions()
    if not subs:
        raise ValueError("subscriptions.list returned 0 items, keeping existing rows")
    blocked = load_blocked()
    subs = [sub for sub in subs if sub[0] not in blocked]
    marks = ",".join("?" * len(blocked))
    for table in ("videos", "channel_activity"):  # drop anything stored before the block
        db.execute(f"DELETE FROM {table} WHERE channel_id IN ({marks})", list(blocked))
    db.executemany("""
        INSERT INTO subscriptions (channel_id, title, thumbnail, synced_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            title = excluded.title,
            thumbnail = excluded.thumbnail,
            synced_at = excluded.synced_at
    """, [(*sub, synced_at) for sub in subs])
    # unsubscribed channels keep an older synced_at
    db.execute("DELETE FROM subscriptions WHERE synced_at != ?", (synced_at,))
    db.commit()
    return len(subs)


def load_channels(db):
    rows = db.execute("SELECT channel_id, title FROM subscriptions").fetchall()
    return [{"channel_id": channel_id, "handle": title} for channel_id, title in rows]


def parse_duration_seconds(duration):
    match = re.fullmatch(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        duration,
    )
    if not match:
        return None  # e.g. P1DT2H for videos over a day, or P0D for live
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


OLD_STREAK_STOP = 10  # consecutive items older than the cutoff before we stop paging
OVERLAP = timedelta(days=1)  # re-scan the previous run's tail to catch premieres going live


def list_upload_ids(api_key, channel_id, published_after):
    # uploads playlist id is the channel id with "UC" swapped for "UU"
    params = {
        "part": "contentDetails",
        "playlistId": "UU" + channel_id[2:],
        "maxResults": 50,
        "key": api_key,
    }
    ids, old_streak = [], 0
    while True:
        response = requests.get(GOOGLE_YT_PLAYLIST_ITEMS_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        for item in data.get("items", []):
            details = item.get("contentDetails", {})
            published_at = details.get("videoPublishedAt")
            if not published_at:  # private or deleted
                continue
            if published_at < published_after:
                # playlist is ordered by upload time, not publish time: a scheduled or
                # formerly private video can sit below older ones, so look a bit further
                old_streak += 1
                if old_streak >= OLD_STREAK_STOP:
                    return ids
                continue
            old_streak = 0
            ids.append(details["videoId"])
        if not data.get("nextPageToken"):
            return ids
        params["pageToken"] = data["nextPageToken"]


def fetch_video_details(api_key, video_ids):
    videos = []
    for start in range(0, len(video_ids), 50):  # videos.list caps at 50 ids
        response = requests.get(
            GOOGLE_YT_VIDEOS_URL,
            params={
                "part": "snippet,contentDetails",
                "id": ",".join(video_ids[start:start + 50]),
                "key": api_key,
            },
            timeout=30,
        )
        response.raise_for_status()
        for item in response.json().get("items", []):
            snippet = item.get("snippet", {})
            if snippet.get("liveBroadcastContent", "none") != "none":
                continue  # live or upcoming: duration is not final, picked up once finished
            duration_seconds = parse_duration_seconds(
                item.get("contentDetails", {}).get("duration", "")
            )
            video_id = item["id"]
            videos.append({
                "video_id": video_id,
                "channel_id": snippet.get("channelId", ""),
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", ""),
                "duration_seconds": duration_seconds or 0,
                # ponytail: duration heuristic, Shorts can be up to 3 min but so can normal videos.
                # Exact check = probe youtube.com/shorts/<id> for a redirect.
                "is_short": int(duration_seconds is not None and duration_seconds <= 180),
                "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
            })
    return videos


def ingest_channel(db, api_key, channel, state, run_started_at):
    channel_id = channel["channel_id"]
    last_run = state.get(channel_id)
    if last_run:
        since = datetime.fromisoformat(last_run.replace("Z", "+00:00")) - OVERLAP
    else:
        since = run_started_at - timedelta(days=10)
    published_after = since.isoformat().replace("+00:00", "Z")

    run_started_at_iso = run_started_at.isoformat().replace("+00:00", "Z")
    ids = list_upload_ids(api_key, channel_id, published_after)
    videos = fetch_video_details(api_key, ids)
    changes_before = db.total_changes
    db.executemany("""
        INSERT OR IGNORE INTO videos (
            video_id, channel_id, title, published_at, duration_seconds, is_short, youtube_url
        ) VALUES (
            :video_id, :channel_id, :title, :published_at, :duration_seconds, :is_short, :youtube_url
        )
    """, videos)
    inserted = db.total_changes - changes_before

    state[channel_id] = run_started_at_iso
    db.execute("""
        INSERT INTO channel_activity (channel_id, handle, last_run_at)
        VALUES (?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            handle = excluded.handle,
            last_run_at = excluded.last_run_at
    """, (channel_id, channel.get("handle"), state[channel_id]))
    db.commit()
    # saved after the commit so a crash re-fetches at worst (INSERT OR IGNORE)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

    return len(ids), inserted


def main():
    load_dotenv(BASE_DIR / ".env")
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("GOOGLE_API_KEY is required")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    run_started_at = datetime.now(timezone.utc).replace(microsecond=0)

    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                title TEXT NOT NULL,
                published_at TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL,
                youtube_url TEXT NOT NULL
            )
        """)
        if "is_short" not in [r[1] for r in db.execute("PRAGMA table_info(videos)")]:
            # rows from the old Shorts-only ingest are all shorts
            db.execute("ALTER TABLE videos ADD COLUMN is_short INTEGER NOT NULL DEFAULT 1")
        db.execute("CREATE INDEX IF NOT EXISTS videos_published ON videos(published_at DESC)")
        db.execute(
            "CREATE INDEX IF NOT EXISTS videos_channel_published ON videos(channel_id, published_at DESC)"
        )
        db.execute("""
            CREATE TABLE IF NOT EXISTS channel_activity (
                channel_id TEXT PRIMARY KEY,
                handle TEXT,
                last_run_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                channel_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                thumbnail TEXT NOT NULL,
                synced_at TEXT NOT NULL
            )
        """)
        try:
            print(f"subscriptions={sync_subscriptions(db, run_started_at.isoformat())}")
        except (OSError, ValueError, RefreshError, requests.RequestException) as err:
            print(f"subscriptions sync failed: {err}", flush=True)
        for channel_id in load_blocked():  # unblocked channels re-backfill like new subs
            state.pop(channel_id, None)
        channels = load_channels(db)
        for channel in channels:
            try:
                found, saved = ingest_channel(db, api_key, channel, state, run_started_at)
                print(f"{channel['handle']}: found={found} new={saved}")
            except requests.RequestException as err:
                print(f"{channel['handle']}: failed {err}", flush=True)

    print(f"done channels={len(channels)}")


if __name__ == "__main__":
    main()
