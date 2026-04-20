# Stack

From `frontend/package.json`.

## Runtime dependencies

| Package | Version | Role |
|---------|---------|------|
| react / react-dom | 18.2.0 | Core framework |
| react-router-dom | 6.21.0 | Client-side routing |
| keycloak-js | 23.0.0 | OAuth2/OIDC client |
| @tanstack/react-query | 5.17.0 | Server state cache + polling |
| zustand | 4.4.0 | Lightweight global state |
| lucide-react | 0.303.0 | Icons |
| react-markdown | 10.1.0 | Markdown renderer |
| remark-gfm | 4.0.1 | GitHub-flavored markdown plugin |
| prismjs | 1.30.0 | Code syntax highlighting |
| mermaid | 11.13.0 | Diagram rendering (designs, ADRs) |
| recharts | 2.15.0 | Analytics charts |

## Dev dependencies

| Package | Version | Role |
|---------|---------|------|
| vite | 5.0.0 | Build / dev server |
| @vitejs/plugin-react | — | Fast refresh |
| tailwindcss | 3.4.0 | Utility CSS |
| postcss / autoprefixer | 8.4.0 / 10.4.0 | CSS processing |
| vitest | 1.1.0 | Unit test runner |
| @testing-library/react | — | Component test helpers |
| @testing-library/jest-dom | — | Assertion matchers |
| @testing-library/user-event | — | Simulated interactions |
| @playwright/test | 1.40.0 | E2E |
| eslint + plugins | 8.55.0 | Lint (react, react-hooks) |

No TypeScript. All files are `.jsx`. (The project template Druppie generates for user apps uses TypeScript; Druppie itself does not.)

## Scripts (npm run)

```
dev        vite
build      vite build → dist/
preview    vite preview
lint       eslint src
test       vitest
test:e2e   playwright test
test:e2e:headed   playwright test --headed
```

## Vite config

`frontend/vite.config.js`:

- `server.host = "0.0.0.0"` — required so the container-bound Vite is reachable from the host at `localhost:5273`.
- `server.port = 5173` — internal container port; docker-compose maps to 5273 externally.
- `define.process.env = {}` — polyfill for Node-assumed libs.
- `test.environment = "jsdom"`, `test.globals = true`, `test.exclude = ["tests/e2e/**", "node_modules/**", "dist/**"]`.
- No path aliases — all imports are relative.

## Production build

```
docker build -f frontend/Dockerfile \
  --build-arg VITE_API_URL=https://… \
  --build-arg VITE_KEYCLOAK_URL=https://… \
  --build-arg VITE_KEYCLOAK_REALM=druppie \
  --build-arg VITE_KEYCLOAK_CLIENT_ID=druppie-frontend \
  -t druppie-frontend .
```

Build args are baked in at build time (Vite inlines `import.meta.env.VITE_*` values). The resulting image is nginx-alpine serving `/dist/`. `Dockerfile.dev` skips the build and just runs `vite` with the source mounted.

## Entry point

`frontend/src/main.jsx`:

```jsx
const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, refetchOnWindowFocus: false } }
});
ReactDOM.createRoot(document.getElementById("root")).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
);
```

`App.jsx`:
- Initializes Keycloak (async).
- Provides `AuthContext` with `{ keycloakReady, authenticated, user }`.
- Shows a spinner while Keycloak is initializing.
- Shows an error screen on init failure (e.g. Keycloak unreachable).
- Mounts `<BrowserRouter>` with the full route tree.
