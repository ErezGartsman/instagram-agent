/// <reference types="vite/client" />

// Typed Cockpit environment variables (see .env.example).
interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string
  readonly VITE_SUPABASE_ANON_KEY: string
  // Legacy Nexus backend (used only by the /legacy app).
  readonly VITE_API_BASE?: string
  readonly VITE_API_URL?: string
  // Set to "off" to disable the dev-only auth bypass under `vite dev`.
  readonly VITE_COCKPIT_DEV_BYPASS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
