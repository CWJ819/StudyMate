import type { SVGProps } from 'react'

type IconProps = {
  className?: string
}

function iconProps(className?: string): SVGProps<SVGSVGElement> {
  return {
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.5,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': true,
    className: className ?? 'size-4 flex-none',
  }
}

export function ChevronDown({ className }: IconProps) {
  return (
    <svg {...iconProps(className)}>
      <path d="m6 9 6 6 6-6" />
    </svg>
  )
}

export function ChevronUp({ className }: IconProps) {
  return (
    <svg {...iconProps(className)}>
      <path d="m6 15 6-6 6 6" />
    </svg>
  )
}

export function ChevronRight({ className }: IconProps) {
  return (
    <svg {...iconProps(className)}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  )
}

export function Search({ className }: IconProps) {
  return (
    <svg {...iconProps(className)}>
      <circle cx="11" cy="11" r="7" />
      <path d="m16.5 16.5 4.5 4.5" />
    </svg>
  )
}

export function X({ className }: IconProps) {
  return (
    <svg {...iconProps(className)}>
      <path d="m6 6 12 12M18 6 6 18" />
    </svg>
  )
}

export function Check({ className }: IconProps) {
  return (
    <svg {...iconProps(className)}>
      <path d="m5 12 4 4L19 6" />
    </svg>
  )
}

export function AlertTriangle({ className }: IconProps) {
  return (
    <svg {...iconProps(className)}>
      <path d="M12 3 2.5 20h19L12 3Z" />
      <path d="M12 9v5" />
      <circle cx="12" cy="17.5" r="0.5" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function Inbox({ className }: IconProps) {
  return (
    <svg {...iconProps(className)}>
      <path d="M4 6h16v12H4z" />
      <path d="M4 14h4l2 3h4l2-3h4" />
    </svg>
  )
}
