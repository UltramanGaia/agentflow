import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

function manualChunks(id: string) {
  if (!id.includes("node_modules")) {
    return;
  }
  if (id.includes("@monaco-editor") || id.includes("monaco-editor")) {
    return "vendor-monaco";
  }
  if (
    id.includes("/reactflow/") ||
    id.includes("/@reactflow/") ||
    id.includes("/d3-") ||
    id.includes("/use-sync-external-store/")
  ) {
    return "vendor-reactflow";
  }
  if (id.includes("/zustand/")) {
    return "vendor-zustand";
  }
  if (id.includes("/react-router") || id.includes("@tanstack/react-query")) {
    return "vendor-router-query";
  }
  if (id.includes("/react/") || id.includes("/react-dom/") || id.includes("/scheduler/")) {
    return "vendor-react-core";
  }
  if (id.includes("/zod/")) {
    return "vendor-validation";
  }
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8877",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.{test,spec}.{ts,tsx}", "src/main.tsx"],
    },
  },
});
