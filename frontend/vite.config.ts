import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    // The app shipped as one ~730KB chunk; split heavy vendors so the browser
    // can cache them separately and parse the main bundle faster.
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("jszip")) return "jszip";
          if (id.includes("lucide")) return "icons";
          if (id.includes("react")) return "react-vendor";
          return "vendor";
        }
      }
    }
  },
  server: {
    port: 5174,
    proxy: {
      "/api": "http://127.0.0.1:8010",
      "/ws": {
        target: "ws://127.0.0.1:8010",
        ws: true
      }
    }
  }
});
