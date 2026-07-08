import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // The dev server runs in a container with the source bind-mounted from the
    // host. Native inotify events don't cross that mount on every host, so Vite
    // never invalidates its module cache on edit and keeps serving stale code
    // (even after a browser hard-refresh). Polling makes file changes reliably
    // detected so HMR / re-reads work. Slightly more CPU; standard for Docker dev.
    watch: {
      usePolling: true,
      interval: 200,
    },
    // The branch-env dev workspace sets VITE_API_URL=/proxy/8000: that path is
    // normally resolved by code-server's port proxy (page served via
    // /proxy/5173). When the dev server is reached DIRECTLY on :5173 there is
    // no code-server in front, so mirror the same prefix-strip here. Unused
    // (and harmless) when VITE_API_URL is an absolute URL, as in docker-compose.
    proxy: {
      '/proxy/8000': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/proxy\/8000/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
  },
  define: {
    'process.env': {}
  },
  test: {
    exclude: ['tests/e2e/**', 'node_modules/**', 'dist/**'],
    environment: 'jsdom',
    globals: true
  }
})
