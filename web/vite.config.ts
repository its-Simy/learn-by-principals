import { fileURLToPath } from "node:url"

import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// The API (`brightlearn web`) listens on 8765; in dev, Vite serves the app and forwards /api to it.
// VITE_API_PORT points the proxy elsewhere, e.g. at scripts/dev_server.py on another port.
const apiPort = process.env.VITE_API_PORT ?? "8765"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // One bundle (about 780 kB) served from localhost, where a split buys no load time; warn only past 1 MB.
  build: { chunkSizeWarningLimit: 1000 },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    proxy: {
      "/api": `http://127.0.0.1:${apiPort}`,
    },
  },
})
