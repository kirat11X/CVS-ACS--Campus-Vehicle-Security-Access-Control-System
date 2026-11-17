import { Capacitor } from "@capacitor/core";

/** true inside the Capacitor Android / iOS app, false in a browser. */
export const isNativeApp = Capacitor.isNativePlatform();
export const platformName = Capacitor.getPlatform(); // "web" | "android" | "ios"

const SERVER_KEY = "campus-console.server";
const BUILD_SERVER = (import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/+$/, "");

/** "http://10.0.0.5:8000/" -> "http://10.0.0.5:8000"; null when it is not an http(s) URL. */
export function normalizeServerUrl(input: string): string | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
  try {
    const url = new URL(withScheme);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return `${url.origin}${url.pathname.replace(/\/+$/, "")}`;
  } catch {
    return null;
  }
}

/** Server address saved on this device (sign-in screen / settings), if any. */
export function storedServerUrl(): string | null {
  try {
    return localStorage.getItem(SERVER_KEY);
  } catch {
    return null;
  }
}

export function saveServerUrl(url: string | null): void {
  try {
    if (url) localStorage.setItem(SERVER_KEY, url);
    else localStorage.removeItem(SERVER_KEY);
  } catch {
    // storage unavailable: the address lasts for this session only
    memoryServer = url;
  }
}

let memoryServer: string | null = null;

/**
 * Base for every API call. Browser: /api through the dev / reverse proxy unless a server
 * was saved. App: the saved server, else the build-time VITE_API_BASE_URL, else "" (unset).
 */
export function apiBase(): string {
  return storedServerUrl() ?? memoryServer ?? (BUILD_SERVER || (isNativeApp ? "" : "/api"));
}

export function serverConfigured(): boolean {
  return apiBase() !== "";
}

/** Human-readable description of where API calls go. */
export function describeServer(): string {
  const base = apiBase();
  if (base === "/api") return `${window.location.origin}/api (proxied)`;
  return base || "Not set";
}
