import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

/**
 * Build/serve config for the frontend in src-next/.
 */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: { input: 'preview.html' },
    outDir: 'dist-preview',
  },
  server: {
    port: 5174,
    open: '/preview.html',
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
});
