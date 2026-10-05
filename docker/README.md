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

## Deploy

Hosted with [deployment-kit](https://github.com/dev-en-m/deployment-kit): push to `main` builds the image (`.github/workflows/deploy.yml`), pushes it to GHCR and redeploys over SSH. Do the kit's one-time server setup (its section 1) first. Merging to `main` triggers a deploy, so finish steps 1-5 below before merging. If the first run fails, re-run it from **Actions → Deploy → Run workflow** once the server is ready. Then, for this app (kit section 2; no Postgres/Redis, the API uses SQLite):

1. DNS: A record for the subdomain pointing at the server IP.
2. On the server, the folder name must equal the GitHub repo name (`loop`):
   ```sh
   mkdir -p /srv/apps/loop/data && cd /srv/apps/loop
   # paste docker/docker-compose.server.yml as docker-compose.yml
   # create .env: IMAGE_TAG=latest plus GOOGLE_API_KEY etc. from api/.env.example
   ```
3. Copy the OAuth token (made locally by `api/auth_youtube.py`): `scp data/token.json demo:/srv/apps/loop/data/`. It already holds the client id/secret, so `client_secret.json` is not needed on the server.
4. As `ubuntu`: `sudo add-site <subdomain> 3001 <email>` (3001 = host port in the compose file, unique per app). Record `loop`, the port and the domain in the kit's port register (README 2.5); if 3001 is taken, change it there and in the compose file.
5. Repo secrets `SERVER_HOST` and `SERVER_SSH_KEY`, then merge the release PR into `main`.
6. First ingest, then daily cron as `deploy`:
   ```sh
   cd /srv/apps/loop && docker compose run --rm app python api/ingest_youtube_shorts.py
   # crontab -e
   0 6 * * * cd /srv/apps/loop && docker compose run --rm app python api/ingest_youtube_shorts.py > data/ingest.log 2>&1   # keeps only the last run, no log growth
   ```

Check: `curl https://<subdomain>/health` returns OK (works before the first ingest); `/api/v1/videos` returns JSON after it. Point the kit's uptime monitor (section 5) at `/health`.

Backups: the kit's backup cron only dumps Postgres. `app.db` can be rebuilt by re-ingesting. `token.json` cannot (needs the browser consent again), so keep the local `data/token.json` or take a Lightsail snapshot. The API does not serve `ui/` or `web/`; host those separately.
