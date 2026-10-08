// Dev-only stand-in for the API: open http://localhost:5173/?mock
// Data is real local rows (web/src/mock.json); ages become dates at load so they never go stale.
import data from "./mock.json";

const videos = data.videos.map(({ age_hours, ...v }) => ({
  ...v,
  published_at: new Date(Date.now() - age_hours * 3600e3).toISOString(),
}));

export default function mockJson(path, { channel_id, kind = "all", sort = "recent", limit = 30, after = 0 }) {
  if (path === "/api/v1/channels") return data.channels;
  const rows = videos
    .filter((v) => !channel_id || v.channel_id === channel_id)
    .filter((v) => kind === "all" || v.is_short === (kind === "short"))
    .sort((a, b) =>
      sort === "views" ? (b.view_count ?? -1) - (a.view_count ?? -1)
      : sort === "oldest" ? a.published_at.localeCompare(b.published_at)
      : b.published_at.localeCompare(a.published_at));
  const end = Number(after) + Number(limit);
  return { data: rows.slice(after, end), nextCursor: end < rows.length ? end : null, hasMore: end < rows.length };
}
