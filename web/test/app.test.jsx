import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "../src/App.jsx";

const video = (over) => ({
  video_id: "abc123",
  url: "https://www.youtube.com/watch?v=abc123",
  title: "Long one",
  channel_id: "c1",
  channel_title: "Chan",
  published_at: "2020-01-01T00:00:00Z",
  duration_seconds: 600,
  is_short: 0,
  view_count: 5,
  thumbnail: null,
  ...over,
});

beforeEach(() => {
  // jsdom has no <dialog> modal support: mimic open/close and the close event
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
    this.dispatchEvent(new Event("close"));
  };
  vi.stubGlobal("fetch", vi.fn(async (url) => ({
    ok: true,
    json: async () =>
      String(url).includes("/channels")
        ? []
        : { data: [video(), video({ video_id: "short1", title: "A short", is_short: 1 })], nextCursor: null },
  })));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const card = (title) => screen.findByRole("link", { name: new RegExp(title) });
const iframe = () => document.querySelector("iframe");

test("a plain click opens the popup with the embed and does not follow the link", async () => {
  render(<App />);
  const link = await card("Long one");
  expect(fireEvent.click(link)).toBe(false); // false = preventDefault was called
  expect(document.querySelector("dialog").open).toBe(true);
  expect(iframe().src).toBe("https://www.youtube-nocookie.com/embed/abc123?autoplay=1&rel=0&playsinline=1");
  expect(screen.getByText("Open on YouTube").href).toBe("https://www.youtube.com/watch?v=abc123");
});

test("a modified click keeps the normal link and opens no popup", async () => {
  render(<App />);
  const link = await card("Long one");
  expect(fireEvent.click(link, { ctrlKey: true })).toBe(true);
  expect(fireEvent.click(link, { metaKey: true })).toBe(true);
  expect(document.querySelector("dialog").open).toBe(false);
  expect(iframe()).toBeNull();
});

test("the close button removes the iframe so the video stops", async () => {
  render(<App />);
  fireEvent.click(await card("Long one"));
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  await waitFor(() => expect(iframe()).toBeNull());
  expect(document.querySelector("dialog").open).toBe(false);
});

test("a click on the backdrop closes the popup", async () => {
  render(<App />);
  fireEvent.click(await card("Long one"));
  fireEvent.click(document.querySelector("dialog"));
  await waitFor(() => expect(iframe()).toBeNull());
});

test("a Short gets the tall frame and a long video the wide one", async () => {
  render(<App />);
  fireEvent.click(await card("Long one"));
  expect(document.querySelector(".frame").className).toBe("frame");
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  fireEvent.click(await card("A short"));
  expect(document.querySelector(".frame").className).toBe("frame tall");
});

test("the list starts on the Long filter", async () => {
  render(<App />);
  await card("Long one");
  expect(screen.getByRole("button", { name: "Long" }).getAttribute("aria-pressed")).toBe("true");
});

test("the account icon shows the initial and points at the coming-soon popover", async () => {
  render(<App />);
  await card("Long one");
  const icon = screen.getByRole("button", { name: "Account" });
  expect(icon.textContent).toBe("D");
  const pop = document.getElementById(icon.getAttribute("popovertarget"));
  expect(pop.hasAttribute("popover")).toBe(true);
  expect(pop.textContent).toBe("Try your own YouTube feed. Coming soon.");
});
