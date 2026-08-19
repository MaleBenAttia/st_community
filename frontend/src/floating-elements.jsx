export function Stm32Chip(props) {
  const pins = Array.from({ length: 6 }, (_, i) => 38 + i * 8);
  return (
    <svg viewBox="0 0 120 120" {...props}>
      <defs>
        <filter id="chip-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {pins.map((y, i) => (
        <g key={i}>
          <rect x="12" y={y} width="10" height="2" rx="1" fill="#8A94A6" />
          <rect x="98" y={y} width="10" height="2" rx="1" fill="#8A94A6" />
        </g>
      ))}
      <rect x="24" y="24" width="72" height="72" rx="6" fill="#03234B" stroke="#00B4E6" strokeWidth="1.5" />
      <rect x="30" y="30" width="60" height="60" rx="4" fill="none" stroke="#8A94A6" strokeWidth="1" opacity="0.5" />
      <circle cx="34" cy="34" r="1.5" fill="#8A94A6" />
      <text x="60" y="63" textAnchor="middle" fontFamily="Consolas, Menlo, monospace" fontSize="10" fill="#00B4E6" letterSpacing="2">STM32</text>
      <circle cx="84" cy="84" r="2.5" fill="#00B4E6" filter="url(#chip-glow)">
        <animate attributeName="opacity" values="0.25;1;0.25" keyTimes="0;0.5;1" calcMode="spline" keySplines="0.42 0 0.58 1;0.42 0 0.58 1" dur="4s" repeatCount="indefinite" />
      </circle>
    </svg>
  );
}

export function CircuitTrace(props) {
  return (
    <svg viewBox="0 0 120 120" {...props}>
      <defs>
        <filter id="trace-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <rect x="10" y="10" width="100" height="100" rx="8" fill="none" stroke="#03234B" strokeWidth="1.5" opacity="0.55" />
      {[[10, 10], [110, 10], [10, 110], [110, 110]].map(([x, y], i) => (
        <g key={i}>
          <line x1={x - 4} y1={y} x2={x + 4} y2={y} stroke="#8A94A6" strokeWidth="1" />
          <line x1={x} y1={y - 4} x2={x} y2={y + 4} stroke="#8A94A6" strokeWidth="1" />
        </g>
      ))}
      <rect x="52" y="48" width="20" height="20" rx="3" fill="#03234B" stroke="#00B4E6" strokeWidth="1.5" />
      {[0, 1].map((i) => (
        <g key={i}>
          <rect x={58 + i * 8} y="44" width="2" height="4" fill="#8A94A6" />
          <rect x={58 + i * 8} y="72" width="2" height="4" fill="#8A94A6" />
          <rect x="48" y={54 + i * 8} width="4" height="2" fill="#8A94A6" />
          <rect x="72" y={54 + i * 8} width="4" height="2" fill="#8A94A6" />
        </g>
      ))}
      <path d="M22 34 H48 V84 H98" fill="none" stroke="#00B4E6" strokeWidth="1.5" />
      <path d="M72 60 H98" fill="none" stroke="#00B4E6" strokeWidth="1.5" opacity="0.7" />
      <circle cx="22" cy="34" r="2.5" fill="#8A94A6" />
      <circle cx="98" cy="84" r="2.5" fill="#8A94A6" />
      <circle cx="98" cy="60" r="2.5" fill="#8A94A6" />
      <circle r="2.5" fill="#00B4E6" filter="url(#trace-glow)">
        <animateMotion dur="6s" repeatCount="indefinite" path="M22 34 H48 V84 H98" />
      </circle>
    </svg>
  );
}

export function EmWave(props) {
  const wavePath = 'M8 60 Q16 44 24 60 T40 60 T56 60 T72 60 T88 60 T104 60';
  return (
    <svg viewBox="0 0 120 120" {...props}>
      <line x1="8" y1="60" x2="112" y2="60" stroke="#8A94A6" strokeWidth="1" strokeDasharray="2 5" opacity="0.5" />
      <path d={wavePath} fill="none" stroke="#8A94A6" strokeWidth="1.5" opacity="0.6" />
      <path d={wavePath} fill="none" stroke="#00B4E6" strokeWidth="1.5" strokeDasharray="16 10" strokeLinecap="round">
        <animate attributeName="stroke-dashoffset" from="0" to="-52" dur="5s" repeatCount="indefinite" />
      </path>
    </svg>
  );
}