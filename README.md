# loop

Your YouTube subscriptions as two feeds:

- `ui/`: full-screen Shorts player (subscribed channels' Shorts only)
- `web/`: video list with an all-channels / per-channel filter and a Shorts / Long toggle
- `api/`: FastAPI + SQLite, plus the ingest script that syncs subscriptions and uploads

## Setup

1. **Google Cloud:** enable YouTube Data API v3. Create an API key and an OAuth client of type Desktop app (download its JSON).
2. **Config:** `cp api/.env.example api/.env`, set `GOOGLE_API_KEY` and `GOOGLE_OAUTH_CLIENT_FILE`.
3. **Python:** `python3 -m venv venv && venv/bin/pip install -r docker/requirements.txt google-auth-oauthlib==1.3.1`
4. **Consent (once):** `mkdir -p data && export DATA_DIR="$PWD/data"`, then `venv/bin/python api/auth_youtube.py`. It saves `token.json` in `DATA_DIR`, and `app.db` lives there too. Keep `DATA_DIR` set in the shell (not in `api/.env`) for steps 5 and 6; the same `data/` directory is what the Docker commands mount. Without it, everything defaults to `api/`.
5. **Ingest:** `venv/bin/python api/ingest_youtube_shorts.py`. First run backfills 10 days per channel. Run it daily (cron example in `docker/README.md`).
6. **API:** `venv/bin/uvicorn api.main:app --port 8000`
7. **Shorts UI:** serve `ui/` statically (for example `python3 -m http.server -d ui 5500`). It reads the API URL from the `api-endpoint` meta tag in `ui/index.html`.
8. **List UI:** `cd web && cp .env.example .env && npm install && npm run dev`. `VITE_API_BASE` points at the API. Local: the `.env.example` default (`http://127.0.0.1:8000`). Netlify (`netlify.toml` builds `web/`): set `VITE_API_BASE` to the public API URL in Site settings → Environment variables. It is baked into the bundle at build time, so it is config, not a secret.

Docker for the API and ingest, and deploy (push to `main` redeploys via GitHub Actions): `docker/README.md`.

## API

| Endpoint | Returns |
| --- | --- |
| `GET /api/v1/videos?limit&after` | Shorts video ids from subscribed channels, newest first |
| `GET /api/v1/channels` | Subscribed channels with video counts |
| `GET /api/v1/library?channel_id&kind=all\|short\|long&sort=recent\|oldest\|views&limit&after` | Video objects, subscribed channels only |
| `GET /health` | `{"ok": true}` |

## Blocked channels

Add a channel id to `api/blocked_channels.txt` to hide it and stop storing its videos. The next ingest run removes its existing rows.

## Tests

`venv/bin/python api/test_main.py` and `venv/bin/python api/test_ingest.py`

## Notes

- A video counts as a Short if it is 3 minutes or shorter (heuristic, see `ponytail:` comment in the ingest script).
- `csv/` holds the old hand-curated channel list; the ingest no longer reads it.
- Project roadmap and workflow: `PLAN.md`, `CLAUDE.md`.
