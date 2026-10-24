import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
    rollupOptions: {
      input: {
        index: resolve(__dirname, "index.html"),
        notch: resolve(__dirname, "notch.html"),
        mobile: resolve(__dirname, "mobile.html"),
        character: resolve(__dirname, "character.html"),
        chat: resolve(__dirname, "chat.html"),
      },
    },
  },
  server: {
    proxy: {
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
      "/api": "http://127.0.0.1:8765",
    },
  },
});
