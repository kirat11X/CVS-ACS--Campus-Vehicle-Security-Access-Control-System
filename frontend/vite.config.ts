import { readFileSync } from "node:fs";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf-8")) as { version: string };

// The web console talks to /api; the dev and preview servers proxy it to the FastAPI
// backend, so no CORS is involved. The Capacitor app has no proxy: it calls the server
// URL entered on its sign-in screen (or VITE_API_BASE_URL baked in at build time).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.BACKEND_URL || "http://127.0.0.1:8000";
  const proxy = {
    "/api": {
      target: backend,
      changeOrigin: true,
      rewrite: (path: string) => path.replace(/^\/api/, ""),
    },
  };
  return {
    plugins: [react()],
    define: { __APP_VERSION__: JSON.stringify(pkg.version) },
    build: {
      rollupOptions: {
        output: {
          // Libraries change less often than the console: separate chunks stay cached across releases.
          manualChunks(id: string) {
            if (!id.includes("node_modules")) return undefined;
            if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return "react";
            if (id.includes("node_modules/react-router")) return "router";
            if (id.includes("node_modules/@tanstack")) return "query";
            if (id.includes("node_modules/@capacitor")) return "capacitor";
            if (id.includes("node_modules/lucide-react")) return "icons";
            return undefined;
          },
        },
      },
    },
    // The native projects hold Gradle / Xcode build output; watching them reloads the page mid-build.
    server: { port: 5173, proxy, watch: { ignored: ["**/android/**", "**/ios/**"] } },
    preview: { port: 4173, proxy },
  };
});
