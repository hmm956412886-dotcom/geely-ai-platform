import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const gatewayUrl = loadEnv(mode, ".", "").AI_GATEWAY_URL || "http://127.0.0.1:8765";

  return {
    base: "/copilot-shell/",
    plugins: [react()],
    build: {
      outDir: "dist",
      emptyOutDir: true,
    },
    server: {
      port: 5173,
      proxy: {
        "/api": gatewayUrl,
        "/plugin-manifest.json": gatewayUrl,
      },
    },
  };
});
