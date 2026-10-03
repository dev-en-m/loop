# Project notes

YouTube Shorts feed from the user's subscribed channels. See `PLAN.md` for the roadmap and slice list.

- `api/` FastAPI + SQLite, ingestion script
- `ui/` existing Shorts UI. Do not edit unless the user says so.
- `web/` list UI (React/Vite), planned
- `docker/` image for the API

## Workflow: vertical slices, one PR each

- Work in vertical slices from `PLAN.md`. One slice = one branch (`feat/...`, `fix/...`, `docs/...`, `chore/...`) cut from an up-to-date `main`.
- Never commit to `main` directly. Keep commits small.
- When a slice is done and verified, push the branch and open a PR with `gh pr create`. Describe the slice and how it was verified.
- After opening the PR, stop. Wait for the user's approval and merge. Do not start the next slice or stack branches on an unmerged one.
- After merge: `git checkout main && git pull`, tick the slice in `PLAN.md`, then branch for the next slice.
- Then continue as normal development: small focused changes, verify before saying done.
