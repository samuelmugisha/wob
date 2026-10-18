/** Awards mark: a figure with arms raised in a gold sweep, with the wordmark. */
export function LogoMark({ size = 44 }: { size?: number }) {
  return (
    <svg width={size} height={size * 1.15} viewBox="0 0 40 46" aria-hidden>
      <defs>
        <linearGradient id="wob-gold" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f3d69a" />
          <stop offset="0.55" stopColor="#d4a65a" />
          <stop offset="1" stopColor="#a8762f" />
        </linearGradient>
      </defs>
      <circle cx="21" cy="7" r="4.2" fill="url(#wob-gold)" />
      <path
        d="M8 4.5c2.5 6 6.4 9.2 11.6 9.6 4.8.3 8.8-2.4 12.4-8.1-1.6 7.7-5.6 12.4-10.4 13.6 3.5 4.6 4.2 10.6 1.9 17.9-1.2 3.9-3.6 6.7-7.1 8.5 2.6-4.4 3.6-8.9 3.1-13.6-.5-4.2-2.2-7.9-5.2-11.1C10.7 17.9 8.6 12.3 8 4.5z"
        fill="url(#wob-gold)"
      />
      <path
        d="M5 30c3.6 6.3 9.4 10 17.2 11.1-6.4 1.7-12.6-.5-16-5.3-1.1-1.6-1.5-3.6-1.2-5.8z"
        fill="url(#wob-gold)"
        opacity="0.85"
      />
    </svg>
  );
}

export default function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`logo${compact ? " compact" : ""}`}>
      <LogoMark size={compact ? 30 : 42} />
      <span className="logo-words">
        <span>Women</span>
        <span>on Boards</span>
        <span className="logo-awards">Awards</span>
      </span>
    </span>
  );
}
