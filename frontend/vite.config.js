import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/static/floating/',
  build: {
    outDir: '../Dashboard/static/floating',
    emptyOutDir: true,
    target: 'es2018',
    rollupOptions: {
      output: {
        entryFileNames: 'index.js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'index[extname]',
      },
    },
  },
});