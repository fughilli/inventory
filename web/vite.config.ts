import { defineConfig } from "vite";

// In dev, the FastAPI server (server/, port 8080) serves the API and photos.
const backend = process.env.INVENTORY_BACKEND ?? "http://127.0.0.1:8080";

export default defineConfig({
  server: {
    host: true,
    proxy: { "/api": backend, "/photos": backend },
  },
  build: { target: "es2022", assetsInlineLimit: 0 },
});
