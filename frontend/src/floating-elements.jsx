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

export function SensorNode(props) {
  return (
    <svg viewBox="0 0 120 120" {...props}>
      <defs>
        <filter id="sensor-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <circle cx="60" cy="60" r="40" fill="none" stroke="#03234B" strokeWidth="1.5" opacity="0.4" strokeDasharray="4 4" />
      <circle cx="60" cy="60" r="25" fill="none" stroke="#8A94A6" strokeWidth="1.5" />
      
      {[0, 60, 120, 180, 240, 300].map((angle, i) => {
        const rad = (angle * Math.PI) / 180;
        const x1 = 60 + 25 * Math.cos(rad);
        const y1 = 60 + 25 * Math.sin(rad);
        const x2 = 60 + 40 * Math.cos(rad);
        const y2 = 60 + 40 * Math.sin(rad);
        return (
          <g key={i}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#8A94A6" strokeWidth="1.5" />
            <circle cx={x2} cy={y2} r="3" fill="#8A94A6" />
          </g>
        );
      })}
      
      <circle cx="60" cy="60" r="10" fill="#03234B" stroke="#00B4E6" strokeWidth="2" />
      <circle cx="60" cy="60" r="4" fill="#00B4E6" filter="url(#sensor-glow)">
        <animate attributeName="r" values="3;6;3" dur="2s" repeatCount="indefinite" />
      </circle>
    </svg>
  );
}

export function SignalGraph(props) {
  return (
    <svg viewBox="0 0 120 120" {...props}>
      <defs>
        <filter id="signal-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="1.5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      
      <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
        <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#8A94A6" strokeWidth="0.5" opacity="0.3" />
      </pattern>
      <rect width="120" height="120" fill="url(#grid)" />
      
      <path d="M0 60 Q20 60 30 30 T60 60 T90 90 T120 60" fill="none" stroke="#00B4E6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <animate attributeName="stroke-dasharray" values="0,200;200,0" dur="4s" repeatCount="indefinite" />
      </path>
      
      <circle cx="0" cy="0" r="3" fill="#00B4E6" filter="url(#signal-glow)">
        <animateMotion dur="4s" repeatCount="indefinite" path="M0 60 Q20 60 30 30 T60 60 T90 90 T120 60" />
      </circle>
    </svg>
  );
}

export function AIChip(props) {
  return (
    <svg viewBox="0 0 120 120" {...props}>
      <defs>
        <filter id="ai-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <polygon points="60,10 105,35 105,85 60,110 15,85 15,35" fill="none" stroke="#03234B" strokeWidth="2" opacity="0.6"/>
      <polygon points="60,20 95,40 95,80 60,100 25,80 25,40" fill="none" stroke="#8A94A6" strokeWidth="1" strokeDasharray="3 3"/>
      
      <circle cx="60" cy="60" r="15" fill="#03234B" stroke="#00B4E6" strokeWidth="1.5" />
      <circle cx="60" cy="60" r="5" fill="#00B4E6" filter="url(#ai-glow)">
         <animate attributeName="r" values="3;8;3" dur="2.5s" repeatCount="indefinite" />
         <animate attributeName="opacity" values="0.5;1;0.5" dur="2.5s" repeatCount="indefinite" />
      </circle>
      
      <line x1="60" y1="45" x2="60" y2="20" stroke="#8A94A6" strokeWidth="1" />
      <line x1="60" y1="75" x2="60" y2="100" stroke="#8A94A6" strokeWidth="1" />
      <line x1="47" y1="52" x2="25" y2="40" stroke="#8A94A6" strokeWidth="1" />
      <line x1="73" y1="52" x2="95" y2="40" stroke="#8A94A6" strokeWidth="1" />
      <line x1="47" y1="68" x2="25" y2="80" stroke="#8A94A6" strokeWidth="1" />
      <line x1="73" y1="68" x2="95" y2="80" stroke="#8A94A6" strokeWidth="1" />
    </svg>
  );
}

export function SiliconWafer(props) {
  return (
    <svg viewBox="0 0 120 120" {...props}>
      <defs>
        <filter id="wafer-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="1.5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <pattern id="wafer-grid" width="8" height="8" patternUnits="userSpaceOnUse">
          <rect width="8" height="8" fill="none" stroke="#00B4E6" strokeWidth="0.5" opacity="0.3" />
        </pattern>
      </defs>
      
      <path d="M 95 90 A 45 45 0 1 0 25 90 L 95 90 Z" fill="url(#wafer-grid)" stroke="#03234B" strokeWidth="2" />
      <path d="M 95 90 A 45 45 0 1 0 25 90 L 95 90 Z" fill="none" stroke="#00B4E6" strokeWidth="1.5" opacity="0.6" />
      
      <line x1="10" y1="60" x2="110" y2="60" stroke="#00B4E6" strokeWidth="1" filter="url(#wafer-glow)">
        <animate attributeName="y1" values="20;90;20" dur="4s" repeatCount="indefinite" />
        <animate attributeName="y2" values="20;90;20" dur="4s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0;1;1;0;0" dur="4s" repeatCount="indefinite" />
      </line>
    </svg>
  );
}

export function QfpPackage(props) {
  const pins = Array.from({ length: 8 }, (_, i) => 24 + i * 10);
  return (
    <svg viewBox="0 0 120 120" {...props}>
      {pins.map((x, i) => (
        <g key={`tb-${i}`}>
          <rect x={x} y="10" width="2" height="12" fill="#8A94A6" />
          <rect x={x} y="98" width="2" height="12" fill="#8A94A6" />
        </g>
      ))}
      {pins.map((y, i) => (
        <g key={`lr-${i}`}>
          <rect x="10" y={y} width="12" height="2" fill="#8A94A6" />
          <rect x="98" y={y} width="12" height="2" fill="#8A94A6" />
        </g>
      ))}
      <rect x="22" y="22" width="76" height="76" rx="4" fill="#03234B" stroke="#00B4E6" strokeWidth="1.5" />
      <rect x="28" y="28" width="64" height="64" rx="2" fill="none" stroke="#8A94A6" strokeWidth="1" opacity="0.5" />
      <circle cx="34" cy="34" r="3" fill="#00B4E6">
         <animate attributeName="opacity" values="0.3;1;0.3" dur="2s" repeatCount="indefinite" />
      </circle>
      <text x="60" y="66" textAnchor="middle" fontFamily="Arial, sans-serif" fontSize="16" fill="#8A94A6" fontWeight="bold">ST</text>
    </svg>
  );
}

export function MosfetSymbol(props) {
  return (
    <svg viewBox="0 0 120 120" {...props}>
       <defs>
        <filter id="mosfet-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      
      <line x1="20" y1="60" x2="45" y2="60" stroke="#8A94A6" strokeWidth="2" />
      <line x1="45" y1="35" x2="45" y2="85" stroke="#00B4E6" strokeWidth="3" />
      
      <line x1="55" y1="35" x2="55" y2="48" stroke="#00B4E6" strokeWidth="3" />
      <line x1="55" y1="54" x2="55" y2="66" stroke="#00B4E6" strokeWidth="3" />
      <line x1="55" y1="72" x2="55" y2="85" stroke="#00B4E6" strokeWidth="3" />
      
      <line x1="55" y1="40" x2="80" y2="40" stroke="#8A94A6" strokeWidth="2" />
      <line x1="80" y1="40" x2="80" y2="20" stroke="#8A94A6" strokeWidth="2" />
      
      <line x1="55" y1="80" x2="80" y2="80" stroke="#8A94A6" strokeWidth="2" />
      <line x1="80" y1="80" x2="80" y2="100" stroke="#8A94A6" strokeWidth="2" />
      
      <line x1="55" y1="60" x2="80" y2="60" stroke="#8A94A6" strokeWidth="2" />
      <line x1="80" y1="60" x2="80" y2="80" stroke="#8A94A6" strokeWidth="2" />
      
      <polygon points="55,60 65,55 65,65" fill="#8A94A6" />
      
      <circle cx="80" cy="40" r="3" fill="#00B4E6" filter="url(#mosfet-glow)">
         <animate attributeName="opacity" values="0.2;1;0.2" dur="2s" repeatCount="indefinite" />
      </circle>
    </svg>
  );
}

export function Stm32Cube3D(props) {
  return (
    <svg viewBox="0 0 120 120" {...props}>
      <defs>
        <filter id="cube-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      
      {/* Top Face */}
      <polygon points="60,15 95,35 60,55 25,35" fill="#03234B" stroke="#00B4E6" strokeWidth="1.5" opacity="0.9" />
      {/* Right Face */}
      <polygon points="60,55 95,35 95,80 60,100" fill="#03234B" stroke="#00B4E6" strokeWidth="1.5" opacity="0.6" />
      {/* Left Face */}
      <polygon points="25,35 60,55 60,100 25,80" fill="#03234B" stroke="#8A94A6" strokeWidth="1.5" opacity="0.4" />
      
      {/* Inner Cube Grid / Lines */}
      <line x1="60" y1="55" x2="60" y2="100" stroke="#00B4E6" strokeWidth="1.5" />
      <line x1="60" y1="55" x2="95" y2="35" stroke="#00B4E6" strokeWidth="1.5" />
      <line x1="60" y1="55" x2="25" y2="35" stroke="#00B4E6" strokeWidth="1.5" />

      {/* Pulsing Vertex Nodes */}
      <circle cx="60" cy="15" r="3" fill="#00B4E6" filter="url(#cube-glow)">
        <animate attributeName="r" values="2;4.5;2" dur="3s" repeatCount="indefinite" />
      </circle>
      <circle cx="60" cy="55" r="3" fill="#00B4E6" filter="url(#cube-glow)">
        <animate attributeName="r" values="3;5;3" dur="2s" repeatCount="indefinite" />
      </circle>
      
      <text x="60" y="82" textAnchor="middle" fontFamily="Consolas, monospace" fontSize="9" fill="#00B4E6" letterSpacing="1" fontWeight="bold">CUBE</text>
    </svg>
  );
}

export function NucleoBoard(props) {
  return (
    <svg viewBox="0 0 120 120" {...props}>
      {/* Board Base Outline */}
      <rect x="25" y="10" width="70" height="100" rx="4" fill="#03234B" stroke="#00B4E6" strokeWidth="1.5" />
      
      {/* ST-LINK Breakaway Line */}
      <line x1="25" y1="32" x2="95" y2="32" stroke="#8A94A6" strokeWidth="1" strokeDasharray="3 2" />
      <text x="60" y="24" textAnchor="middle" fontFamily="sans-serif" fontSize="7" fill="#8A94A6" letterSpacing="1">ST-LINK</text>
      
      {/* ST Morpho Headers (Left & Right double-row connectors) */}
      <rect x="28" y="38" width="4" height="66" fill="#8A94A6" />
      <rect x="34" y="38" width="4" height="66" fill="#8A94A6" opacity="0.6" />
      <rect x="82" y="38" width="4" height="66" fill="#8A94A6" opacity="0.6" />
      <rect x="88" y="38" width="4" height="66" fill="#8A94A6" />
      
      {/* Central STM32 MCU */}
      <rect x="47" y="55" width="26" height="26" rx="2" fill="#03234B" stroke="#00B4E6" strokeWidth="1.2" />
      <circle cx="51" cy="59" r="1" fill="#00B4E6" />
      <text x="60" y="70" textAnchor="middle" fontFamily="sans-serif" fontSize="6" fill="#00B4E6" fontWeight="bold">STM32</text>
      
      {/* Reset Button (Blue) & User Button (Black/Yellow) */}
      <rect x="44" y="94" width="8" height="6" rx="1" fill="#00B4E6" />
      <rect x="68" y="94" width="8" height="6" rx="1" fill="#8A94A6" />
    </svg>
  );
}

export function CortexMCore(props) {
  return (
    <svg viewBox="0 0 120 120" {...props}>
      <defs>
        <filter id="cortex-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="1.5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      
      {/* Outer CPU Block */}
      <rect x="15" y="20" width="90" height="80" rx="6" fill="#03234B" stroke="#8A94A6" strokeWidth="1.5" opacity="0.8" />
      
      {/* Core Header */}
      <rect x="15" y="20" width="90" height="20" rx="6" fill="#03234B" stroke="#00B4E6" strokeWidth="1.5" />
      <text x="60" y="34" textAnchor="middle" fontFamily="sans-serif" fontSize="9" fill="#00B4E6" fontWeight="bold" letterSpacing="1">ARM CORTEX-M</text>
      
      {/* Sub-blocks: NVIC, MPU, CPU */}
      <rect x="22" y="48" width="22" height="20" rx="2" fill="none" stroke="#8A94A6" strokeWidth="1" />
      <text x="33" y="61" textAnchor="middle" fontFamily="sans-serif" fontSize="6" fill="#8A94A6">NVIC</text>
      
      <rect x="49" y="48" width="22" height="20" rx="2" fill="none" stroke="#8A94A6" strokeWidth="1" />
      <text x="60" y="61" textAnchor="middle" fontFamily="sans-serif" fontSize="6" fill="#8A94A6">MPU</text>
      
      <rect x="76" y="48" width="22" height="20" rx="2" fill="none" stroke="#00B4E6" strokeWidth="1" />
      <text x="87" y="61" textAnchor="middle" fontFamily="sans-serif" fontSize="6" fill="#00B4E6">FPU</text>
      
      {/* Internal Bus */}
      <line x1="22" y1="82" x2="98" y2="82" stroke="#00B4E6" strokeWidth="2" strokeDasharray="4 2" />
      
      <circle cx="22" cy="82" r="2.5" fill="#00B4E6" filter="url(#cortex-glow)">
        <animate attributeName="cx" values="22;98;22" dur="3s" repeatCount="indefinite" />
      </circle>
    </svg>
  );
}