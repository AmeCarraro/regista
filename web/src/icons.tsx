// The icons of the page, drawn here as SVG: no icon font and no download.
// They take the color and the size of the text around them.
import type { ReactNode, SVGProps } from 'react'

type Props = SVGProps<SVGSVGElement>

function Icon({ children, ...props }: Props & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  )
}

/** The mark of the app: a spark, the one who gives the cue. */
export function Logo(props: Props) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" {...props}>
      <defs>
        <linearGradient id="logo-fill" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ff8a5b" />
          <stop offset="0.55" stopColor="#e052a0" />
          <stop offset="1" stopColor="#7a5cff" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="28" height="28" rx="9" fill="url(#logo-fill)" />
      <path d="M16 7.5l2.3 6.2 6.2 2.3-6.2 2.3L16 24.5l-2.3-6.2-6.2-2.3 6.2-2.3z" fill="#fff" />
    </svg>
  )
}

export const Chip = (props: Props) => (
  <Icon {...props}>
    <rect x="6" y="6" width="12" height="12" rx="2.5" />
    <rect x="9.75" y="9.75" width="4.5" height="4.5" rx="1" />
    <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
  </Icon>
)

export const Spark = (props: Props) => (
  <Icon {...props}>
    <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" />
    <path d="M19 15l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z" />
  </Icon>
)

export const Search = (props: Props) => (
  <Icon {...props}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4.5 4.5" />
  </Icon>
)

export const Picture = (props: Props) => (
  <Icon {...props}>
    <rect x="3.5" y="4.5" width="17" height="15" rx="3" />
    <circle cx="9" cy="10" r="1.6" />
    <path d="M4 17l4.5-4.5 3.5 3.5 3-3 5 5" />
  </Icon>
)

export const Layers = (props: Props) => (
  <Icon {...props}>
    <path d="M12 3.5l9 4.8-9 4.8-9-4.8z" />
    <path d="M3 12.5l9 4.8 9-4.8M3 16.7l9 4.8 9-4.8" />
  </Icon>
)

export const Bolt = (props: Props) => (
  <Icon {...props}>
    <path d="M13 2.5L5 13.5h6l-1 8 8-11h-6z" />
  </Icon>
)

export const Talk = (props: Props) => (
  <Icon {...props}>
    <path d="M4.5 6.5a3 3 0 0 1 3-3h9a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3H12l-4.5 4v-4a3 3 0 0 1-3-3z" />
  </Icon>
)

export const Check = (props: Props) => (
  <Icon {...props}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Icon>
)

export const Cross = (props: Props) => (
  <Icon {...props}>
    <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
  </Icon>
)

export const Arrow = (props: Props) => (
  <Icon {...props}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Icon>
)

export const Back = (props: Props) => (
  <Icon {...props}>
    <path d="M19 12H5M11 6l-6 6 6 6" />
  </Icon>
)

export const Down = (props: Props) => (
  <Icon {...props}>
    <path d="M6 9.5l6 6 6-6" />
  </Icon>
)

export const Stop = (props: Props) => (
  <Icon {...props}>
    <rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" />
  </Icon>
)

export const Send = (props: Props) => (
  <Icon {...props}>
    <path d="M12 19V5M6 11l6-6 6 6" />
  </Icon>
)

export const Refresh = (props: Props) => (
  <Icon {...props}>
    <path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3" />
    <path d="M19.5 4.5v4h-4" />
  </Icon>
)

export const Menu = (props: Props) => (
  <Icon {...props}>
    <path d="M4.5 7h15M4.5 12h15M4.5 17h15" />
  </Icon>
)

export const Sun = (props: Props) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8" />
  </Icon>
)

export const Moon = (props: Props) => (
  <Icon {...props}>
    <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
  </Icon>
)

export const Eye = (props: Props) => (
  <Icon {...props}>
    <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
    <circle cx="12" cy="12" r="2.8" />
  </Icon>
)

export const Trash = (props: Props) => (
  <Icon {...props}>
    <path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 12.5h9l1-12.5M10 11v5M14 11v5" />
  </Icon>
)

export const Folder = (props: Props) => (
  <Icon {...props}>
    <path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" />
  </Icon>
)

export const Undo = (props: Props) => (
  <Icon {...props}>
    <path d="M8.5 5L4 9.5 8.5 14" />
    <path d="M4 9.5h10a5.5 5.5 0 0 1 0 11h-3.5" />
  </Icon>
)

export const Dog = (props: Props) => (
  <Icon {...props}>
    <path d="M6 9l-2.5-3.5L8 4.5l2 2h4l2-2 4.5 1L18 9v5a6 6 0 0 1-12 0z" />
    <path d="M10 12.5v.5M14 12.5v.5M11 16h2" />
  </Icon>
)

export const Church = (props: Props) => (
  <Icon {...props}>
    <path d="M12 2.5v4M10 4.5h4M8 21v-9l4-4 4 4v9M4 21v-6l4-2M20 21v-6l-4-2M3 21h18M12 21v-4" />
  </Icon>
)
