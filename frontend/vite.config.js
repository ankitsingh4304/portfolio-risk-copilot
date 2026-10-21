import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, calls to /api go to the FastAPI server on port 8000.
export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 900 },
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
});
