# Docker

The image runs the API and the ingest script. The one-time OAuth consent runs on the host (it needs a browser), see the root README.

Build from the repository root:

```sh
docker build -f docker/Dockerfile -t yt-tech-shorts-api .
```

Data lives in a host directory so `token.json` (from the consent step) and `app.db` are shared with the container:

```sh
mkdir -p data
DATA_DIR="$PWD/data" venv/bin/python api/auth_youtube.py   # or, if you already consented: cp api/token.json data/
```

Set `DATA_DIR` in the shell, not in `api/.env`: `--env-file api/.env` would override the image's `DATA_DIR=/app/data` and the container would look for a host path.

Run ingestion (syncs subscriptions, then fetches new uploads). This creates/updates `data/app.db`:

```sh
docker run --rm --env-file api/.env -v "$PWD/data:/app/data" yt-tech-shorts-api python api/ingest_youtube_shorts.py
```

Run the API against the same directory:

```sh
docker run --rm -p 8000:8000 -v "$PWD/data:/app/data" yt-tech-shorts-api
```

Run ingestion daily, for example with cron (`crontab -e`):

```cron
0 6 * * * cd /path/to/yt-tech-shorts && docker run --rm --env-file api/.env -v "$PWD/data:/app/data" yt-tech-shorts-api python api/ingest_youtube_shorts.py >> data/ingest.log 2>&1
```

If the OAuth consent screen is in "Testing" status the refresh token expires after 7 days and ingest logs `subscriptions sync failed`. Publish the app or re-run `auth_youtube.py`.
