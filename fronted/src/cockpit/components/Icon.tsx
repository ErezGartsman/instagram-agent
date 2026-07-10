import type { SVGProps } from 'react'

export type IconName =
  | 'grid'
  | 'columns'
  | 'inbox'
  | 'sparkle'
  | 'logout'
  | 'mail'
  | 'check'
  | 'alert'
  | 'arrowRight'
  | 'clock'
  | 'queue'
  | 'chart'
  | 'x'
  | 'send'
  | 'refresh'
  | 'zap'
  | 'branch'
  | 'bell'
  | 'flag'
  | 'shield'
  | 'play'

type Props = { name: IconName; size?: number } & Omit<SVGProps<SVGSVGElement>, 'name'>

/**
 * Inline, dependency-free icon set. Single stroke weight, currentColor — so an
 * icon simply inherits the text colour of its container (muted, ink, accent…).
 */
export function Icon({ name, size = 18, ...rest }: Props) {
  const common: SVGProps<SVGSVGElement> = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': true,
    ...rest,
  }

  switch (name) {
    case 'grid':
      return (
        <svg {...common}>
          <rect x="3" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="3" width="7" height="7" rx="1.5" />
          <rect x="3" y="14" width="7" height="7" rx="1.5" />
          <rect x="14" y="14" width="7" height="7" rx="1.5" />
        </svg>
      )
    case 'columns':
      return (
        <svg {...common}>
          <rect x="3" y="4" width="5" height="16" rx="1.5" />
          <rect x="9.5" y="4" width="5" height="16" rx="1.5" />
          <rect x="16" y="4" width="5" height="16" rx="1.5" />
        </svg>
      )
    case 'inbox':
      return (
        <svg {...common}>
          <path d="M22 12h-6l-2 3h-4l-2-3H2" />
          <path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z" />
        </svg>
      )
    case 'sparkle':
      return (
        <svg {...common}>
          <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6L12 2z" />
        </svg>
      )
    case 'logout':
      return (
        <svg {...common}>
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
          <polyline points="16 17 21 12 16 7" />
          <line x1="21" y1="12" x2="9" y2="12" />
        </svg>
      )
    case 'mail':
      return (
        <svg {...common}>
          <rect x="2" y="4" width="20" height="16" rx="2" />
          <path d="m22 7-10 6L2 7" />
        </svg>
      )
    case 'check':
      return (
        <svg {...common}>
          <polyline points="20 6 9 17 4 12" />
        </svg>
      )
    case 'alert':
      return (
        <svg {...common}>
          <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h16.9a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      )
    case 'arrowRight':
      return (
        <svg {...common}>
          <line x1="5" y1="12" x2="19" y2="12" />
          <polyline points="12 5 19 12 12 19" />
        </svg>
      )
    case 'clock':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <polyline points="12 7 12 12 15 14" />
        </svg>
      )
    case 'queue':
      return (
        <svg {...common}>
          <line x1="4" y1="6" x2="20" y2="6" />
          <line x1="4" y1="12" x2="14" y2="12" />
          <line x1="4" y1="18" x2="10" y2="18" />
        </svg>
      )
    case 'chart':
      return (
        <svg {...common}>
          <line x1="4" y1="20" x2="20" y2="20" />
          <rect x="6" y="11" width="3" height="6" rx="0.5" />
          <rect x="11" y="7" width="3" height="10" rx="0.5" />
          <rect x="16" y="13" width="3" height="4" rx="0.5" />
        </svg>
      )
    case 'x':
      return (
        <svg {...common}>
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      )
    case 'send':
      return (
        <svg {...common}>
          <path d="M22 2 11 13" />
          <path d="M22 2 15 22 11 13 2 9z" />
        </svg>
      )
    case 'refresh':
      return (
        <svg {...common}>
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
          <path d="M3 3v5h5" />
        </svg>
      )
    case 'zap':
      return (
        <svg {...common}>
          <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />
        </svg>
      )
    case 'branch':
      return (
        <svg {...common}>
          <circle cx="6" cy="6" r="2.5" />
          <circle cx="6" cy="18" r="2.5" />
          <circle cx="18" cy="12" r="2.5" />
          <path d="M6 8.5v3a3 3 0 0 0 3 3h6.5" />
          <path d="M6 15.5v-3" opacity="0" />
          <path d="M15.5 9.5 18 12l-2.5 2.5" opacity="0" />
        </svg>
      )
    case 'bell':
      return (
        <svg {...common}>
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
      )
    case 'flag':
      return (
        <svg {...common}>
          <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V4s-1 1-4 1-5-2-8-2-4 1-4 1z" />
          <line x1="4" y1="22" x2="4" y2="15" />
        </svg>
      )
    case 'shield':
      return (
        <svg {...common}>
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
      )
    case 'play':
      return (
        <svg {...common}>
          <polygon points="6 4 20 12 6 20 6 4" />
        </svg>
      )
  }
}
