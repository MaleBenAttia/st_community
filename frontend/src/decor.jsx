import React from 'react';
import { Stm32Chip, CircuitTrace, EmWave } from './floating-elements.jsx';
import './floating.css';

const POOL = [
  Stm32Chip, Stm32Chip, Stm32Chip, Stm32Chip, Stm32Chip, Stm32Chip,
  Stm32Chip, Stm32Chip, Stm32Chip, Stm32Chip, Stm32Chip, Stm32Chip,
  CircuitTrace, CircuitTrace, CircuitTrace, CircuitTrace,
  EmWave, EmWave, EmWave, EmWave,
];
const COUNT = POOL.length;
const DRIFTS = ['driftA', 'driftB', 'driftC', 'driftD'];

const rand = (min, max) => min + Math.random() * (max - min);
const isChip = (Comp) => Comp === Stm32Chip;

const ITEMS = Array.from({ length: COUNT }, (_, i) => {
  const Comp = POOL[i % POOL.length];
  return {
    Comp,
    top: rand(2, 90),
    left: rand(2, 90),
    size: Math.round(isChip(Comp) ? rand(36, 62) : rand(42, 72)),
    opacity: +rand(0.15, 0.4).toFixed(2),
    drift: DRIFTS[i % DRIFTS.length],
    dur: Math.round(rand(35, 80)),
    delay: -Math.round(rand(0, 40)),
    blur: +rand(0, 0.6).toFixed(1),
  };
});

export default function FloatingDecor() {
  return (
    <div className="floating-decor">
      {ITEMS.map((it, i) => {
        const { Comp } = it;
        return (
          <div
            key={i}
            className="fe"
            style={{
              top: it.top + '%',
              left: it.left + '%',
              width: it.size,
              height: it.size,
              opacity: it.opacity,
              filter: `drop-shadow(0 2px 6px rgba(15, 23, 42, 0.15)) blur(${it.blur}px)`,
              animation: `${it.drift} ${it.dur}s ease-in-out ${it.delay}s infinite alternate`,
            }}
          >
            <Comp />
          </div>
        );
      })}
    </div>
  );
}