import { useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";
const KINDS = [
  ["all", "All"],
  ["short", "Shorts"],
  ["long", "Long"],
];

async function getJson(path, params = {}, signal) {
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

export default function App() {
  const [channels, setChannels] = useState([]);
  const [channelId, setChannelId] = useState("");
  const [kind, setKind] = useState("all");
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
      { channel_id: channelId, kind, limit: 30, after },
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
  }, [channelId, kind]);

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
        {videos.map((v) => (
          <a key={v.video_id} className="card" href={v.url} target="_blank" rel="noreferrer">
            <div className="thumb">
              <img src={v.thumbnail} alt="" loading="lazy" />
              <span>{formatDuration(v.duration_seconds)}</span>
            </div>
            <h3>{v.title}</h3>
            <p>
              {v.channel_title} · {new Date(v.published_at).toLocaleDateString()}
              {v.is_short && " · Short"}
            </p>
          </a>
        ))}
      </div>

      {cursor !== null && (
        <button className="more" disabled={loading} onClick={() => load(cursor)}>
          {loading ? "Loading..." : "Load more"}
        </button>
      )}
    </main>
  );
}
