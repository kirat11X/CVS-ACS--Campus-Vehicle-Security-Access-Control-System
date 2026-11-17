/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute backend URL baked into a build (e.g. for the mobile app). Default: /api (web) or none (app). */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare const __APP_VERSION__: string;
