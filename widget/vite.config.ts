import { defineConfig } from "vitest/config";
import preact from "@preact/preset-vite";
export default defineConfig({
  plugins: [preact()],
  server: { port: 5174 },
  build: {
    lib: {
      entry: "src/main.tsx",
      name: "MunimWidget",
      fileName: () => "widget.js",
      formats: ["iife"],
    },
  },
  test: { environment: "jsdom" },
});
