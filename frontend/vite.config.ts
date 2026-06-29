import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import tsconfigPaths from "vite-tsconfig-paths";

export default defineConfig({
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
    tsconfigPaths(),
  ],
  server: {
    host: true,
    port: 3000,
    proxy: {
      "/api": {
        target: process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8100",
        changeOrigin: true,
      },
      "/health": {
        target: process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8100",
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: true,
    port: 3000,
    proxy: {
      "/api": {
        target: process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8100",
        changeOrigin: true,
      },
      "/health": {
        target: process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8100",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
