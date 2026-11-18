import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run build` writes to dist/, which gateway.py serves.
// `npm run dev` serves on :5173 and forwards /api to the gateway on :8080.
// `npm test` runs the Vitest suite in src/**/*.test.{js,jsx} (jsdom, no gateway needed).
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8080", changeOrigin: true } },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
