# Project notes

YouTube Shorts feed from the user's subscribed channels. See `PLAN.md` for the roadmap and slice list.

- `api/` FastAPI + SQLite, ingestion script
- `ui/` existing Shorts UI. Do not edit unless the user says so.
- `web/` list UI (React/Vite), planned
- `docker/` image for the API

## Workflow: vertical slices, one PR each, via `develop`

- `main` is the deploy branch: every push to `main` deploys. Do not touch `main` (no commits, no PRs to it) unless the user says to release.
- `develop` is the integration branch. Slice PRs target `develop`.
- Work in vertical slices from `PLAN.md`. One slice = one branch (`feat/...`, `fix/...`, `docs/...`, `chore/...`) cut from an up-to-date `develop`.
- Never commit to `develop` or `main` directly. Keep commits small.
- When a slice is done and verified, push the branch and open a PR with `gh pr create --base develop`. Describe the slice and how it was verified.
- After opening the PR, stop. Wait for the user's approval and merge. Do not start the next slice or stack branches on an unmerged one.
- After merge: `git checkout develop && git pull`, tick the slice in `PLAN.md` (on a branch, PR to `develop`), then branch for the next slice.
- Release: only when the user asks, open a PR `develop` -> `main` with `gh pr create --base main --head develop`. Merging it deploys. The server must be ready first (see `docker/README.md`, "Deploy").
- Then continue as normal development: small focused changes, verify before saying done.
