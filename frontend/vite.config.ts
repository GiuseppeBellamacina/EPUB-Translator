import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const proxyTarget = process.env.VITE_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    // Docker Desktop on Windows does not forward file events into the container:
    // poll the bind-mounted sources, or edits are never picked up.
    watch: process.env.VITE_WATCH_POLLING
      ? { usePolling: true, interval: 500 }
      : undefined,
    proxy: {
      "/api": proxyTarget,
      "/ws": {
        target: proxyTarget.replace(/^http/, "ws"),
        ws: true,
      },
    },
  },
});
