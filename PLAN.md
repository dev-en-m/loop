# Plan: subscribed-channels feed + list UI

Tick a slice only after its PR is merged.

## Context
Today the app ingests a hand-curated CSV of channels (`csv/channels_with_ids.csv`) and serves Shorts only via `ui/`. Goal: source channels from the user's own YouTube subscriptions (OAuth), keep all uploads (Shorts flagged), add a new React/Vite list UI with all-channels / per-channel filters, and make the existing `ui/` show only subscribed-channel Shorts **without editing `ui/`**.

Decisions (from user): OAuth subscriptions; single user; one-time CLI consent; all uploads with `is_short` flag; `/api/v1/videos` becomes subscribed-only; new React/Vite UI in own folder; uploads-playlist ingestion; daily run, 10-day window.

## Backend (`api/`)
1. **`api/auth_youtube.py`** (new, run once): `google-auth-oauthlib` InstalledAppFlow, scope `youtube.readonly`, saves refresh token to `DATA_DIR/token.json` (gitignored). Needs `GOOGLE_OAUTH_CLIENT_FILE` in `.env.example`.
2. **Sync in `api/ingest_youtube_shorts.py`** (rework, keep file/entrypoint so Dockerfile + README stay valid):
   - Load creds from `token.json`, auto-refresh.
   - `subscriptions.list(mine=true, part=snippet, maxResults=50)` paged -> upsert into new `subscriptions(channel_id PK, title, thumbnail, synced_at)`; delete rows for unsubscribed channels.
   - Per channel: uploads playlist id = `"UU" + channel_id[2:]`; `playlistItems.list` (1 unit) paged until `publishedAt < cutoff` (state file `last_run_by_channel.json` reused for incremental cutoff, first run = now-10d).
   - `videos.list` in batches of **50 ids** (`part=snippet,contentDetails`), parse duration with existing `parse_duration_seconds`; store `is_short = duration <= 180` (heuristic, noted with `ponytail:` comment; exact check would need `/shorts/ID` redirect probe).
   - Catch `requests.RequestException` per channel (not only HTTPError); write state per channel after commit.
   - Schema migration: `ALTER TABLE videos ADD COLUMN is_short INTEGER NOT NULL DEFAULT 1` guarded by PRAGMA check; `CREATE INDEX videos_published ON videos(published_at DESC)` and `videos(channel_id, published_at DESC)`. Store all uploads, not just <=60s.
3. **`api/main.py`**:
   - `/api/v1/videos` + `/get-videos` (unchanged contract: `data` = list of ids, `nextCursor`, `hasMore`): add `JOIN subscriptions` and `WHERE is_short=1`. This is what scopes `ui/` with zero edits. Old curated rows drop out of the feed automatically.
   - New `GET /api/v1/channels` -> `[{channel_id,title,thumbnail,video_count}]`.
   - New `GET /api/v1/library?channel_id=&kind=all|short|long&limit=&after=` -> full video objects (id, title, channel, published_at, duration, is_short, thumbnail url `https://i.ytimg.com/vi/{id}/hqdefault.jpg`). Reuse the existing `limit/after` offset pagination pattern in `get_videos` (keeps shape consistent; keyset deferred).
   - Reuse `DB_PATH`/`DATA_DIR` and CORS setup as is.

## List UI (`web/`, new Vite + React)
- Pages: single page. Top: channel filter (All + per-channel dropdown/sidebar from `/channels`), kind toggle (All / Shorts / Long). Grid of video cards (thumb, title, channel, date, duration) linking to `https://www.youtube.com/watch?v=ID`. "Load more" using `hasMore`/`nextCursor`.
- API base from `VITE_API_BASE` env.
- `ui/` untouched.

## Infra
- `docker/requirements.txt`: add `google-auth`, `google-auth-oauthlib`, pin versions.
- `docker/Dockerfile`: also copy `api/auth_youtube.py`; note token.json lives in the data volume.
- `docker/README.md` + root `README.md` (currently empty): setup order = create OAuth client -> run `auth_youtube.py` -> run ingest (daily cron / scheduler) -> run API -> serve `ui/` and `web/`.
- `.gitignore`: add `token.json`, `client_secret*.json`, `web/node_modules`, `web/dist`.

## Delivery: vertical slices, one PR each
Not one big change. Each slice = own branch off fresh `main`, own PR, **stop and wait for user approval/merge** before starting the next. After approval: first copy this plan to `PLAN.md` at repo root and create `CLAUDE.md` (workflow rules below) on branch `docs/plan-and-workflow`, PR, wait.

Slices (each independently shippable and verifiable):
- [ ] 1. `docs/plan-and-workflow`: `PLAN.md` + `CLAUDE.md`.
- [ ] 2. `feat/oauth-subscriptions`: `auth_youtube.py`, `subscriptions` table, subscription sync, requirements/.env/.gitignore. Verify: table filled with real subs.
- [ ] 3. `feat/uploads-ingest`: uploads-playlist ingest, 50-id batching, `is_short`, indexes/migration, per-channel error handling. Verify: videos rows + quota sane.
- [ ] 4. `feat/subscribed-shorts-feed`: `/api/v1/videos` JOIN subscriptions + `is_short=1`. Verify: unchanged `ui/` shows only subscribed Shorts.
- [ ] 5. `feat/library-api`: `/api/v1/channels`, `/api/v1/library`.
- [ ] 6. `feat/web-list-ui`: `web/` React/Vite with channel + kind filters.
- [ ] 7. `chore/docker-readme`: Dockerfile/requirements pins, daily schedule docs, root README.

`CLAUDE.md` content (workflow section):
- Work in vertical slices; one slice = one branch (`feat/...`, `fix/...`, `docs/...`) from up-to-date `main`.
- Never commit to `main` directly. Commit small, then push and open a PR (`gh pr create`) describing the slice and how it was verified.
- After opening the PR, stop. Wait for user approval/merge. Do not start the next slice, or stack branches, until the PR is merged.
- After merge: `git checkout main && git pull`, then branch for next slice from `PLAN.md`.
- Do not edit `ui/` (existing Shorts UI) unless user says so.
- Keep `PLAN.md` slice list updated (tick off merged slices).

## Verification
1. Run `auth_youtube.py`, confirm `token.json` created.
2. Run ingest: log shows subscription count, per-channel found/saved; sqlite check `SELECT COUNT(*) FROM subscriptions; SELECT is_short,COUNT(*) FROM videos GROUP BY 1;`. Re-run -> no duplicates, quota use low.
- [ ] 3. `curl /api/v1/videos?limit=5` returns only ids from subscribed channels, all `is_short=1`; `/api/v1/channels`, `/api/v1/library?channel_id=X&kind=long` return expected rows.
4. Open `ui/index.html` (unchanged) -> plays only subscribed Shorts. Open `web/` (`npm run dev`) -> All vs per-channel filter and kind toggle change results; Load more works.
5. Unsubscribe a channel, re-run sync -> it disappears from both UIs.

## Out of scope / noted
Multi-user, web OAuth login, exact Shorts detection, keyset pagination, deleting stored videos of unsubscribed channels (just hidden by JOIN).
