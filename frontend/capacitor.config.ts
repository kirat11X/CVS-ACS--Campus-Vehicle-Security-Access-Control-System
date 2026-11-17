import type { CapacitorConfig } from "@capacitor/cli";

// Native shell for the same React build (npm run cap:sync). The app has no /api proxy:
// guards enter the backend address on the sign-in screen (stored on the device).
const config: CapacitorConfig = {
  appId: "com.campusgate.console",
  appName: "Gate Console",
  webDir: "dist",
  server: {
    // Pages load from https://localhost (Android) / capacitor://localhost (iOS); both are in
    // the backend's default CORS_ALLOW_ORIGINS.
    androidScheme: "https",
    // During development the backend is usually a LAN address over plain HTTP.
    // Use an HTTPS backend in production and turn this off.
    cleartext: true,
  },
  android: {
    // Allows the https://localhost page to call an http:// backend on the campus network.
    allowMixedContent: true,
    // Android 15 draws apps edge to edge; keep the console clear of the system bars.
    adjustMarginsForEdgeToEdge: "auto",
  },
};

export default config;
