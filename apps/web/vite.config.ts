import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite dev server proxies /api → FastAPI on :8000. SSE works natively
// over the proxy as long as we don't enable buffering. The plain
// http-proxy adapter Vite uses respects Cache-Control: no-cache,
// which is the only header SSE streams need.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
