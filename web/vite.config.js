import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  if (mode === "production" && !loadEnv(mode, ".", "VITE_").VITE_API_BASE) {
    throw new Error("VITE_API_BASE is not set: set it in the Netlify site env vars");
  }
  return { plugins: [react()] };
});
