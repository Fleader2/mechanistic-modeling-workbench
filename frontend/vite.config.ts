import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Points at the FastAPI app (`uvicorn app.main:app --reload`, default port
// 8000) during local development. Override with VITE_API_BASE_URL.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
