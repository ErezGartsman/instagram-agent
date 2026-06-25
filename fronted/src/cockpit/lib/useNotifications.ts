import { useCallback, useState } from 'react'

// Persists the user's opt-in preference across sessions.
// Permission itself lives in the browser and can't be stored here.
const PREF_KEY = 'nexus.cockpit.notif.v1'

export type NotifPref =
  | 'unavailable' // browser does not support the Notifications API
  | 'denied'      // user explicitly blocked via browser dialog
  | 'off'         // supported + grantable, but user hasn't opted in
  | 'on'          // granted + opted in — notifications active

function deriveInitialPref(): NotifPref {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unavailable'
  if (Notification.permission === 'denied') return 'denied'
  try {
    return localStorage.getItem(PREF_KEY) === 'on' ? 'on' : 'off'
  } catch {
    return 'off'
  }
}

/**
 * Manages Web Notification permission and the in-app opt-in preference.
 *
 * Design constraints (per Erez's directive):
 *   • NEVER auto-request permission on page load — that's hostile UX.
 *   • Permission request only fires from a deliberate user action (toggle).
 *   • `notify()` is a no-op unless permission is granted AND preference is 'on'.
 */
export function useNotifications(): {
  pref: NotifPref
  /** Call from a button/toggle click — triggers the browser permission dialog if needed. */
  enable: () => Promise<void>
  /** Stores 'off' preference; cannot revoke browser permission (browser limitation). */
  disable: () => void
  /** Fire an OS notification. Silent no-op if pref !== 'on' or permission not granted. */
  notify: (title: string, body: string) => void
} {
  const [pref, setPref] = useState<NotifPref>(deriveInitialPref)

  const enable = useCallback(async () => {
    if (!('Notification' in window)) return
    // The browser dialog only fires if permission is 'default'. If already 'granted',
    // requestPermission resolves immediately to 'granted'.
    const result = await Notification.requestPermission()
    if (result === 'granted') {
      try { localStorage.setItem(PREF_KEY, 'on') } catch { /* storage unavailable */ }
      setPref('on')
    } else {
      // 'denied' — user blocked; we can't ask again (browser enforces this).
      setPref('denied')
    }
  }, [])

  const disable = useCallback(() => {
    try { localStorage.setItem(PREF_KEY, 'off') } catch { /* storage unavailable */ }
    setPref('off')
  }, [])

  const notify = useCallback(
    (title: string, body: string) => {
      if (pref !== 'on') return
      if (!('Notification' in window) || Notification.permission !== 'granted') return
      try {
        // tag deduplicates: a rapid burst of leads shows one notification, not N.
        const n = new Notification(title, { body, tag: 'nexus-hot-lead' })
        n.onclick = () => { window.focus(); n.close() }
        setTimeout(() => n.close(), 8_000)
      } catch { /* Notification constructor can throw in some environments */ }
    },
    [pref],
  )

  return { pref, enable, disable, notify }
}
