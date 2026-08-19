import React from 'react';
import { createRoot } from 'react-dom/client';
import FloatingDecor from './decor.jsx';

const container = document.getElementById('floating-decor');
if (container) {
  createRoot(container).render(<FloatingDecor />);
}