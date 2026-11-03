export function XMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={className} aria-hidden style={{ filter: "drop-shadow(0 0 6px rgba(60,245,154,0.55))" }}>
      <defs>
        <linearGradient id="xg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3cf59a" />
          <stop offset="0.55" stopColor="#45d9f5" />
          <stop offset="1" stopColor="#7c8cff" />
        </linearGradient>
      </defs>
      <path d="M6 5 L16 15 L26 5 M6 27 L16 17 L26 27" fill="none" stroke="url(#xg)" strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="16" cy="16" r="1.6" fill="#3cf59a" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="inline-flex items-center gap-2.5">
      <XMark size={24} />
      <span className="font-display text-[15px] font-semibold tracking-[0.32em] x-phosphor">X</span>
    </span>
  );
}
