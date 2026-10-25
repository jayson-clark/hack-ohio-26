import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import process from "node:process";

// `pnpm dev` serves the UI on :5173 and forwards /api to a board server
// (BOARD_URL, default a local `make board` on :8790).
const board = process.env.BOARD_URL || "http://localhost:8790";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: {
    port: 5173,
    proxy: { "/api": { target: board, changeOrigin: true } },
  },
});
