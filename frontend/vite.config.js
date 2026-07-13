import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In the branch-env dev workspace the app is served through code-server's port
// proxy at https://<slug>-dev.rijnland.dev/proxy/5173 — there VITE_API_URL is
// the relative /proxy/8000. Vite's HMR client would otherwise dial a bare
// ws://<host>:5173, which that HTTPS proxy chain doesn't expose, so it fails
// and every edit degrades to a full page reload. Detect that case so we can
// point the HMR websocket back through the proxy instead. Gated on the relative
// API URL so docker-compose / local dev (absolute VITE_API_URL) keep Vite's
// default same-origin HMR untouched.
const inCodeServerProxy = (process.env.VITE_API_URL || '').startsWith('/proxy')

export default defineConfig({
  plugins: [react()],
  // code-server's port proxy serves the app under the /proxy/5173/ path but
  // does NOT rewrite absolute asset URLs, so with the default base='/' the
  // browser fetches /@vite/client and /src/main.jsx from the host root
  // (bypassing the proxy) -> 404 -> blank page. Setting base makes Vite emit
  // /proxy/5173/-prefixed URLs that route back through code-server. Only in the
  // workspace; local/compose keep base='/'.
  ...(inCodeServerProxy && { base: './' }),
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Route the HMR websocket through code-server's /proxy/5173 (wss on 443)
    // so edits hot-reload instead of forcing a full page refresh. The vite-hmr
    // websocket is matched by sub-protocol, not path, so it still resolves
    // after code-server strips the /proxy/5173 prefix. Only set in the
    // workspace; when accessed via the noVNC desktop on localhost:5173 HMR
    // falls back to a (now redirect-free) full reload.
    ...(inCodeServerProxy && {
      // The workspace is reached at druppie-<slug>-dev.rijnland.dev. Vite 5.4+
      // rejects unknown Host headers by default (DNS-rebinding guard), which
      // surfaces as "Blocked request. This host is not allowed." Allow the
      // rijnland.dev wildcard so every branch-env workspace host passes; the
      // dev server sits behind the workspace's oauth2-proxy on that ingress
      // anyway. (localhost is always allowed, so the noVNC desktop still works.)
      allowedHosts: ['.rijnland.dev'],
      hmr: {
        protocol: 'wss',
        clientPort: 443,
        path: '/proxy/5173/',
      },
    }),
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
