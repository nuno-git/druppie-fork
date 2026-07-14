# Developer environment secrets

> One secret layout for every environment. A developer's dev workspace is a
> first-class environment, so it owns its secrets the same way `main` and
> `colab-dev` do.

## The model — every environment has the same shape

```
ai-team-k8s (KV v2 mount)
└── druppie/
    ├── main/                          # prod
    │   ├── app        {internal-api-key, module-api-token, sandbox-api-secret,
    │   │               zai/deepseek/deepinfra/foundry/openrouter-api-key}
    │   ├── database   {url, password}
    │   ├── gitea      {admin-password, db-password, password, token}
    │   ├── keycloak   {admin-user, admin-password, db-password}
    │   └── mcps/*     {data-access, azuredevops, prreviews}
    ├── colab-dev/                     # dev  (identical shape)
    │   └── …
    └── developers/
        ├── robbe/                     # Robbe's dev environment
        │   ├── app        {…}
        │   ├── database   {url, password}
        │   ├── gitea      {…}
        │   ├── keycloak   {…}
        │   ├── workspace  {client-secret, cookie-secret}   ← oauth2-proxy
        │   └── mcps/data-access {data-source-N}
        └── nuno/                      # Nuno's dev environment
            ├── app …, database …, gitea …, keycloak …, workspace …

# Shared (not env-specific):
ai-team-k8s/ci/gitea          {token}   → EXTERNAL_GITEA_TOKEN (all envs)
ai-team-k8s/ci/harbor         {…}       → harbor-regcred
```

Rule of thumb: **if a secret is per-environment, it lives under that environment's path.** Only truly shared credentials (the external Gitea admin token, Harbor robot) stay under `ci/`.

The `workspace` sub-path (oauth2-proxy `client-secret` + `cookie-secret`) only exists on environments that **run** a workspace — i.e. developer envs. `main`/`colab-dev` don't have one (they run baked backend/frontend, no code-server).

## How it flows into the cluster

```
Vault druppie/developers/<user>/*   ──(ESO polls 1 min)──▶  ExternalSecret
                                                              │  target: <instance>-secrets
                                                              ▼
                                            K8s Secret <instance>-secrets (in the env namespace)
                                                              │
                                                              ▼  pod envFrom
                                            workspace/backend containers
```

- **ExternalSecret** lives in the env's namespace, reads `druppie/developers/<user>/{database,keycloak,gitea,app}`, writes `<instance>-secrets`.
- It is rendered by the chart when `devWorkspace.enabled=true` **and** `devWorkspace.developer=<user>` (see `templates/dev-workspace-secrets.yaml`).
- Requires `externalSecrets.managed=true` (ESO owns the Secret; the chart's own `secrets.yaml` is skipped).
- The oauth2-proxy secret is a second ExternalSecret reading `druppie/developers/<user>/workspace` → `workspace-oauth` (`templates/dev-workspace-externalsecret.yaml`).

## Deploying a developer env

```bash
helm upgrade --install druppie ./helm/druppie -n druppie-dev-robbe --create-namespace \
  -f helm/druppie/values.yaml -f helm/druppie/values-rijnland.yaml \
  --set global.instance=druppie-dev-robbe \
  --set global.domain=druppie-dev-robbe.rijnland.dev \
  --set externalSecrets.managed=true \
  --set devWorkspace.enabled=true \
  --set devWorkspace.developer=robbe \
  --set devWorkspace.stackMode=real \
  --set devWorkspace.gitBranch=colab-dev \
  --set devWorkspace.codeServer.devHost=druppie-dev-robbe-dev.rijnland.dev \
  --set devWorkspace.oauth.issuerUrl=https://druppie-dev-robbe.rijnland.dev/realms/druppie
```

The `database.url` stored in Vault must match the env's DB Service DNS:
`postgresql://druppie:<password>@<instance>-druppie-db:5432/druppie` where `<instance>` = `global.instance`.

## Seeding a new developer (Vault writes)

Vault is **read-only from the cluster** — secrets are written via the Vault API/UI
with a token that has write access to `ai-team-k8s/*`. See
`scripts/seed-developer-env.py` — point it at a new `<user>` and it will:

1. Read `druppie/colab-dev/app` for shared LLM-key defaults.
2. Generate per-env randoms for `database`, `keycloak`, `gitea`.
3. Copy the shared `branch-env/workspace-oauth` into `<user>/workspace`.
4. Write `druppie/developers/<user>/{database,keycloak,gitea,app,workspace}`.

The developer can then edit any value in the Vault UI (e.g. paste their personal
`zai-api-key` into `<user>/app`).

### Future: self-service (no admin needed)
Today seeding is manual. To make it self-service, add either:
- a **Kubernetes Job** (runs once per new developer env) that writes the Vault
  paths using a Vault token stored in a bootstrap secret, **or**
- a **backend "create developer env" API** that calls the Vault API with a
  service-account token before deploying the HelmRelease.

Both would call the same Vault writes as `seed-developer-env.py`.

## Migration notes
- The legacy shared `branch-env/workspace-oauth` and `branch-env-secrets` (which
  borrowed `druppie/colab-dev/app`) are superseded. Once all envs move to
  `developers/<user>/*`, those can be retired.
- Robbe's old flat `druppie/developers/robbe` (upper-case keys) has been folded
  into `…/robbe/app` (+ `…/robbe/mcps/data-access`); the flat path can be deleted
  after confirming nothing reads it.
