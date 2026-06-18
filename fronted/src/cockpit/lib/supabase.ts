import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

/**
 * True only when both Supabase env vars are present. The login screen reads this
 * to show a clear "not configured" message instead of failing cryptically.
 */
export const isSupabaseConfigured = Boolean(url && anonKey)

if (!isSupabaseConfigured && import.meta.env.DEV) {
  console.warn(
    '[cockpit] Missing VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY. ' +
      'Copy .env.example → .env.local and fill them in, then restart the dev server.',
  )
}

/**
 * The browser Supabase client. The anon key is the public, RLS-protected
 * publishable key — safe to ship to the browser. `detectSessionInUrl` + the PKCE
 * flow let the magic-link callback complete the sign-in when the user lands back
 * on the app. Placeholders keep createClient from throwing when env is missing;
 * real usage is gated by `isSupabaseConfigured`.
 */
export const supabase = createClient(
  url ?? 'https://placeholder.supabase.co',
  anonKey ?? 'placeholder-anon-key',
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      flowType: 'pkce',
    },
  },
)
