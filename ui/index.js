"use strict";

const API_ENDPOINT = (() => {
  const el = document.querySelector('meta[name="api-endpoint"]');
  return el?.content || `${window.location.origin}/api/v1/videos`;
})();

const PAGE_SIZE = 30;
const LOAD_AHEAD = 5;
// Players kept either side of the active short. iOS WebKit runs out of memory
// with dozens of YouTube iframes and renders them all black.
const KEEP_AROUND = 2;

let players = new Map();
let videoIds = [];
let nextCursor = null;
let hasMore = true;
let isFetching = false;
let observer = null;
let activeIndex = -1;
let ytReady = false;
let audioUnlocked = false;

const track = document.getElementById("track");

async function fetchVideos() {
  if (isFetching || !hasMore) return;

  isFetching = true;
  const url = new URL(API_ENDPOINT);
  url.searchParams.set("limit", String(PAGE_SIZE));
  if (nextCursor) url.searchParams.set("after", nextCursor);

  try {
    const res = await fetch(url.toString());
    if (!res.ok) return;

    const body = await res.json();
    const ids = Array.isArray(body?.data) ? body.data : [];
    const startIndex = videoIds.length;
    videoIds.push(...ids);
    nextCursor = body.nextCursor ?? null;
    hasMore = body.hasMore ?? false;
    appendSlides(ids, startIndex);
  } finally {
    isFetching = false;
  }
}

function appendSlides(ids, startIndex) {
  ids.forEach((videoId, offset) => {
    const index = startIndex + offset;
    const slide = document.createElement("section");
    const mount = document.createElement("div");

    slide.className = "slide";
    slide.dataset.index = String(index);
    mount.id = `yt-${index}`;

    slide.appendChild(mount);
    track.appendChild(slide);

    if (observer) observer.observe(slide);
  });

  syncPlayers(Math.max(activeIndex, 0));
}

function syncPlayers(index) {
  for (const [playerIndex, player] of players) {
    if (Math.abs(playerIndex - index) <= KEEP_AROUND) continue;
    try { player.destroy(); } catch (_) {}
    players.delete(playerIndex);
    const mount = document.createElement("div");
    mount.id = `yt-${playerIndex}`;
    document.querySelector(`.slide[data-index="${playerIndex}"]`)?.replaceChildren(mount);
  }

  if (!ytReady) return;
  const last = Math.min(videoIds.length - 1, index + KEEP_AROUND);
  for (let i = Math.max(0, index - KEEP_AROUND); i <= last; i++) createPlayer(i, videoIds[i]);
}

function createPlayer(index, videoId) {
  if (players.has(index) || !document.getElementById(`yt-${index}`)) return;

  players.set(index, new YT.Player(`yt-${index}`, { // eslint-disable-line no-undef
    videoId,
    playerVars: {
      autoplay: 0,
      controls: 0,
      disablekb: 1,
      fs: 0,
      iv_load_policy: 3,
      loop: 0,
      modestbranding: 1,
      mute: audioUnlocked ? 0 : 1,
      playsinline: 1,
      rel: 0,
    },
    events: {
      onReady: () => {
        if (index === activeIndex) playOnly(index);
      },
      onStateChange: (event) => {
        if (index === activeIndex && event.data === YT.PlayerState.ENDED) { // eslint-disable-line no-undef
          showNext();
        }
      },
    },
  }));
}

function playOnly(index) {
  activeIndex = index;
  syncPlayers(index);

  for (const [playerIndex, player] of players) {
    try {
      if (playerIndex === index) {
        if (audioUnlocked) player.unMute();
        player.playVideo();
      } else {
        player.pauseVideo();
      }
    } catch (_) {}
  }

  if (videoIds.length - index <= LOAD_AHEAD) fetchVideos();
  setTimeout(() => playMutedIfBlocked(index), 1500);
}

// iOS refuses unmuted play that did not start inside a tap, which leaves the
// short paused. Fall back to muted play; the next tap tries sound again.
function playMutedIfBlocked(index) {
  const player = players.get(index);
  if (index !== activeIndex || !player?.getPlayerState) return;

  const { UNSTARTED, PAUSED, CUED } = YT.PlayerState; // eslint-disable-line no-undef
  if (![UNSTARTED, PAUSED, CUED].includes(player.getPlayerState())) return;

  audioUnlocked = false; // stop unmuting on every swipe until the next tap
  player.mute();
  player.playVideo();
}

async function showNext() {
  const nextIndex = activeIndex + 1;
  if (nextIndex >= videoIds.length) await fetchVideos();

  document
    .querySelector(`.slide[data-index="${nextIndex}"]`)
    ?.scrollIntoView();
}

function unlockAudio() {
  audioUnlocked = true;
  const player = players.get(activeIndex);

  try {
    player?.unMute();
    player?.playVideo();
  } catch (_) {}
  setTimeout(() => playMutedIfBlocked(activeIndex), 1500);
}

function observeSlides() {
  observer = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];

    if (!visible) return;
    playOnly(Number(visible.target.dataset.index));
  }, { threshold: 0.75 });

  document.querySelectorAll(".slide").forEach((slide) => observer.observe(slide));
}

window.onYouTubeIframeAPIReady = () => {
  ytReady = true;
  syncPlayers(Math.max(activeIndex, 0));
};

// click, not touchstart/pointerdown: iOS only counts a finished tap as a user gesture.
// Not once: if iOS still blocks sound, playMutedIfBlocked mutes and the next tap retries.
["click", "wheel", "keydown"].forEach((eventName) => {
  window.addEventListener(eventName, unlockAudio, { passive: true });
});

observeSlides();
fetchVideos();
