import { PageHeader } from '../components/PageHeader'
import { useAuth } from '../auth/AuthProvider'
import { useNotifications } from '../lib/useNotifications'

// ── Toggle switch ──────────────────────────────────────────────────────────────
// h-6 × w-11 track, h-5 × w-5 thumb. Off = raised surface + line border.
// On = accent gold. Thumb is always ink (white) for maximum contrast.
function ToggleSwitch({
  on,
  onToggle,
  disabled = false,
  id,
}: {
  on: boolean
  onToggle: () => void
  disabled?: boolean
  id?: string
}) {
  return (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={on}
      disabled={disabled}
      onClick={onToggle}
      className={`relative inline-flex h-6 w-11 shrink-0 rounded-full transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-glow focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:cursor-not-allowed disabled:opacity-40 ${
        on ? 'bg-accent' : 'border border-line bg-raised'
      }`}
    >
      <span
        aria-hidden
        className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-ink shadow-sm transition-transform duration-200 ${
          on ? 'translate-x-5' : 'translate-x-0'
        }`}
      />
    </button>
  )
}

// ── Settings section card ──────────────────────────────────────────────────────
function SettingsSection({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section>
      <h2 className="mb-3 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
        {title}
      </h2>
      <div className="overflow-hidden rounded-card border border-line bg-surface [box-shadow:var(--shadow-card)]">
        {children}
      </div>
    </section>
  )
}

// ── Settings row ───────────────────────────────────────────────────────────────
function SettingsRow({
  label,
  description,
  control,
}: {
  label: string
  description?: string
  control: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-6 px-5 py-4">
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink">{label}</p>
        {description && (
          <p className="mt-0.5 text-xs leading-relaxed text-muted">{description}</p>
        )}
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  )
}

// ── SettingsPage ──────────────────────────────────────────────────────────────

/**
 * The cockpit Settings page — minimal for P1, built to grow.
 *
 * P1 scope:
 *   • Account (read-only identity from the auth session)
 *   • Notifications (hot-lead alert toggle — permanent home after AvatarMenu)
 *
 * Access: AvatarMenu → Settings. Not in the sidebar nav (operator-tool pattern).
 */
export function SettingsPage() {
  const { avatarUrl, displayName, user } = useAuth()
  const { pref, enable, disable } = useNotifications()

  const email = user?.email ?? ''
  const initial = displayName.charAt(0).toUpperCase()
  const imgOk = Boolean(avatarUrl)

  const notifOn      = pref === 'on'
  const notifDenied  = pref === 'denied'
  const notifUnavail = pref === 'unavailable'

  const handleNotifToggle = () => {
    if (notifOn) disable()
    else void enable()
  }

  return (
    <div className="mx-auto max-w-[640px]">
      <PageHeader title="Settings" subtitle="Manage your account and notification preferences." />

      <div className="flex flex-col gap-6">
        {/* ── Account ────────────────────────────────────────────────────── */}
        <SettingsSection title="Account">
          <div className="flex items-center gap-4 px-5 py-4">
            {/* Avatar */}
            <span className="grid h-12 w-12 shrink-0 place-items-center overflow-hidden rounded-full ring-1 ring-line">
              {imgOk ? (
                <img
                  src={avatarUrl!}
                  alt=""
                  referrerPolicy="no-referrer"
                  className="h-full w-full object-cover"
                />
              ) : (
                <span className="grid h-full w-full place-items-center rounded-full bg-accent font-mono text-sm font-semibold text-bg">
                  {initial}
                </span>
              )}
            </span>
            {/* Identity */}
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ink">{displayName}</p>
              <p className="mt-0.5 truncate text-xs text-faint">{email}</p>
            </div>
            <p className="ml-auto shrink-0 text-[11px] text-faint">
              Managed via Google
            </p>
          </div>
        </SettingsSection>

        {/* ── Notifications ──────────────────────────────────────────────── */}
        {!notifUnavail && (
          <SettingsSection title="Notifications">
            <SettingsRow
              label="Hot lead alerts"
              description={
                notifDenied
                  ? 'Notifications are blocked in your browser settings. To enable, open browser Site Settings and allow notifications for this site.'
                  : 'Get an in-app toast and OS notification when a high-confidence lead enters your queue (confidence ≥ 70%).'
              }
              control={
                <ToggleSwitch
                  on={notifOn}
                  onToggle={handleNotifToggle}
                  disabled={notifDenied}
                  id="setting-notif-hot-leads"
                />
              }
            />
          </SettingsSection>
        )}
      </div>
    </div>
  )
}
