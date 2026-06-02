import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
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
