import { useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";
const KINDS = [
  ["all", "All"],
  ["short", "Shorts"],
  ["long", "Long"],
];
const SORTS = [
  ["recent", "Most recent"],
  ["views", "Most viewed"],
  ["oldest", "Oldest first"],
];

// dev only: ?mock serves web/src/mock.js instead of the API (dropped from prod builds)
const MOCK = import.meta.env.DEV && new URLSearchParams(location.search).has("mock");

async function getJson(path, params = {}, signal) {
  if (MOCK) return (await import("./mock.js")).default(path, params);
  const url = new URL(`${API}${path}`);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function formatDuration(total) {
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

// "just now", "17 minutes ago", "2 days ago"; plain date once it is over a month old
function formatWhen(iso) {
  const mins = Math.round((Date.now() - new Date(iso)) / 6e4);
  if (mins < 1) return "just now";
  if (mins < 60) return relative.format(-mins, "minute");
  if (mins < 1440) return relative.format(-Math.round(mins / 60), "hour");
  if (mins < 43200) return relative.format(-Math.round(mins / 1440), "day");
  return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function initials(name) {
  return name.split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

export default function App() {
  const [channels, setChannels] = useState([]);
  const [channelId, setChannelId] = useState("");
  const [kind, setKind] = useState("all");
  const [sort, setSort] = useState("recent");
  const [videos, setVideos] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef(null);

  useEffect(() => {
    getJson("/api/v1/channels").then(setChannels).catch((e) => setError(e.message));
  }, []);

  // after = 0 starts a fresh list, otherwise appends the next page
  function load(after) {
    controller.current?.abort(); // a slower older request must not overwrite newer filters
    controller.current = new AbortController();
    setLoading(true);
    setError("");
    getJson(
      "/api/v1/library",
      { channel_id: channelId, kind, sort, limit: 30, after },
      controller.current.signal,
    )
      .then((body) => {
        setVideos((prev) => {
          if (!after) return body.data;
          // offset paging: new ingests can shift rows and repeat ones already shown
          const seen = new Set(prev.map((v) => v.video_id));
          return [...prev, ...body.data.filter((v) => !seen.has(v.video_id))];
        });
        setCursor(body.nextCursor);
        setLoading(false);
      })
      .catch((e) => {
        if (e.name === "AbortError") return;
        setError(e.message);
        setLoading(false);
      });
  }

  useEffect(() => {
    load(0);
    return () => controller.current?.abort();
  }, [channelId, kind, sort]);

  return (
    <main>
      <header>
        <select aria-label="Channel" value={channelId} onChange={(e) => setChannelId(e.target.value)}>
          <option value="">All channels ({channels.length})</option>
          {channels.map((c) => (
            <option key={c.channel_id} value={c.channel_id}>
              {c.title} ({c.video_count})
            </option>
          ))}
        </select>
        <select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)}>
          {SORTS.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <div className="kinds">
          {KINDS.map(([value, label]) => (
            <button
              key={value}
              className={kind === value ? "on" : ""}
              aria-pressed={kind === value}
              onClick={() => setKind(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      {error && <p className="error">Could not load: {error}</p>}
      {!loading && !error && videos.length === 0 && <p className="empty">No videos.</p>}

      <div className="grid">
        {videos.map((v) => {
          const avatar = channels.find((c) => c.channel_id === v.channel_id)?.thumbnail;
          const fresh = Date.now() - new Date(v.published_at) < 864e5;
          return (
            <a key={v.video_id} className="card" href={v.url} target="_blank" rel="noreferrer">
              <div className="thumb">
                {v.thumbnail && <img src={v.thumbnail} alt="" loading="lazy" />}
                <span>{formatDuration(v.duration_seconds)}</span>
              </div>
              <div className="top">
                <div className="avatar">
                  {avatar ? <img src={avatar} alt="" loading="lazy" /> : initials(v.channel_title)}
                </div>
                <strong>{v.channel_title}</strong>
                <span className="tag">{fresh && "New "}{v.is_short ? "Short" : "Video"}</span>
              </div>
              <h3>{v.title}</h3>
              <p>
                <time dateTime={v.published_at}>{formatWhen(v.published_at)}</time>
                {v.view_count != null && ` · ${v.view_count.toLocaleString()} views`}
              </p>
            </a>
          );
        })}
      </div>

      {cursor !== null && (
        <button className="more" disabled={loading} onClick={() => load(cursor)}>
          {loading ? "Loading..." : "Load more"}
        </button>
      )}
    </main>
  );
}
