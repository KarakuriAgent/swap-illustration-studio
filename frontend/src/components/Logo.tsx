export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
      <rect x="2" y="5" width="11" height="18" rx="3" fill="none" stroke="#E61E1E" strokeWidth="2.5" />
      <rect x="15" y="5" width="11" height="18" rx="3" fill="none" stroke="#1E5AE6" strokeWidth="2.5" />
    </svg>
  )
}
