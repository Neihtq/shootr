import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev server proxies /api to the engine so the browser sees one origin.
// The engine binds 127.0.0.1 only (design 10 §1 rule 4).
export default defineConfig({
  // Relative asset paths so the build works served from /ui/ by the
  // engine (bundled mode) as well as from / by the dev server.
  base: "./",
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8721",
    },
  },
});
