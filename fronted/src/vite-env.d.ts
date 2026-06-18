/// <reference types="vite/client" />

// Typed Cockpit environment variables (see .env.example).
interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string
  readonly VITE_SUPABASE_ANON_KEY: string
  // Legacy Nexus backend (used only by the /legacy app).
  readonly VITE_API_BASE?: string
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
