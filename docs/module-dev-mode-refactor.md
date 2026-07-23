# Refactor: Eliminate embedModules — Always Separate Module Pods

## Problem

Feature branches embed all 13 MCP modules into the workspace pod (uid 1000).
Production/colab-dev runs them as separate pods (uid 0). This causes:

1. **Ownership mismatch** — sandbox runs as root, host-side clone runs as uid 1000
2. **Network policy differences** — embedded modules share workspace network
3. **Env var leaks** — embedded inherits all workspace env
4. **Resource contention** — all modules share one pod's resources
5. **Testing inconsistency** — code behaves differently per environment

## Solution

**Always run modules as separate Deployment pods.** When `devWorkspace.enabled`
and a module is in `devWorkspace.embedModules`, the pod runs from source on the
workspace PVC (hot-reload via `uvicorn --reload`) instead of a baked image.

This eliminates all environment differences while keeping hot-reload on dev
branches.

## Storage

No RWX needed. The workspace PVC (`<fullname>-workspace-dev`) is RWO. Multiple
pods can mount the same RWO PVC **on the same node**. The chart already has
`druppie.sharedStorageAffinity` + `druppie.io/shared-storage: "true"` label for
this. The deploy script already pins all pods to one node via
`nodeSelector.kubernetes.io/hostname`.

## Architecture

```
BEFORE (feature branch):
  workspace pod (uid 1000)
    ├── backend (uvicorn --reload)
    ├── frontend (vite)
    ├── code-server
    ├── mcp coding   (uvicorn --reload, uid 1000)  ← causes ownership bug
    ├── mcp docker   (uvicorn --reload, uid 1000)
    └── ... 11 more modules

AFTER (feature branch):
  workspace pod (uid 1000)
    ├── backend (uvicorn --reload)
    ├── frontend (vite)
    └── code-server

  module-coding pod (uid 0, root)
    └── uvicorn --reload from /workspace PVC

  module-docker pod (uid 0, root)
    └── uvicorn --reload from /workspace PVC

  ... one pod per module, all pinned to same node via affinity
```

## Files to Change

### 1. NEW: `scripts/module-dev-entrypoint.sh`

Generic entrypoint for dev-mode module pods. Takes module key + dir + port.

```bash
#!/usr/bin/env bash
set -euo pipefail

# Args: $1=module-key  $2=module-dir  $3=port
KEY="${1:?module key required}"
DIR="${2:?module dir required}"
PORT="${3:?port required}"

WORKSPACE="/workspace"
REPO="${WORKSPACE}/druppie"
MOD_DIR="${REPO}/mcp-servers/${DIR}"
VENV="${WORKSPACE}/.venvs/${KEY}"
BAKED="/opt/venvs/${KEY}"
DEP_DIR="${WORKSPACE}/.dep-hashes"
REQ="${MOD_DIR}/requirements.txt"
SHA_FILE="${DEP_DIR}/mcp-${KEY}.sha"

mkdir -p "${DEP_DIR}"

# 1. Seed venv from baked snapshot if missing
if [ ! -d "${VENV}" ] && [ -d "${BAKED}" ]; then
  echo "[module-dev] seeding venv from baked snapshot"
  cp -a "${BAKED}" "${VENV}"
fi

# 2. Create venv if still missing
if [ ! -d "${VENV}" ]; then
  echo "[module-dev] creating fresh venv"
  python3 -m venv "${VENV}"
  "${VENV}/bin/pip" install --no-cache-dir --upgrade pip
fi

# 3. Check deps — reinstall if requirements.txt changed
if [ -f "${REQ}" ]; then
  CUR=$(sha256sum "${REQ}" | cut -d' ' -f1)
  OLD=$(cat "${SHA_FILE}" 2>/dev/null || echo "")
  if [ "${CUR}" != "${OLD}" ]; then
    echo "[module-dev] deps changed — pip install"
    "${VENV}/bin/pip" install --no-cache-dir -r "${REQ}" && echo "${CUR}" > "${SHA_FILE}"
  else
    echo "[module-dev] deps unchanged — reusing venv"
  fi
fi

# 4. Launch uvicorn from source with hot-reload
echo "[module-dev] starting ${KEY} on 0.0.0.0:${PORT} from ${DIR}"
cd "${MOD_DIR}"
exec "${VENV}/bin/python" -m uvicorn server:app \
  --host 0.0.0.0 --port "${PORT}" \
  --reload --reload-dir "${MOD_DIR}"
```

### 2. NEW: `helm/druppie/templates/_module-dev-configmap.yaml`

ConfigMap holding the entrypoint script. Avoids image rebuilds.

```yaml
{{- if .Values.devWorkspace.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "druppie.fullname" . }}-module-dev-entrypoint
  labels:
    {{- include "druppie.labels" . | nindent 4 }}
data:
  module-dev-entrypoint.sh: |
{{ .Files.Get "scripts/module-dev-entrypoint.sh" | indent 4 }}
{{- end }}
```

### 3. `_helpers.tpl`

#### 3a. Replace `druppie.moduleEmbedded` with `druppie.moduleDevMode`

The helper stays the same logic but gets a new name reflecting the new
semantics: "should this module run in dev mode (from source on PVC)?"

```go-template
{{/*
Module dev-mode predicate: returns "true" when devWorkspace is enabled AND
the given module key appears in devWorkspace.embedModules — i.e. that module
should run from source on the workspace PVC (uvicorn --reload) instead of as
a baked-image Deployment.

Usage: {{ $dev := include "druppie.moduleDevMode" (dict "root" . "mod" "coding") }}
*/}}
{{- define "druppie.moduleDevMode" -}}
{{- if and .root.Values.devWorkspace.enabled (has .mod .root.Values.devWorkspace.embedModules) -}}true{{- end -}}
{{- end -}}
```

#### 3b. NEW: `druppie.moduleDevImage`

Returns the dev-workspace image when in dev mode, else the baked module image.

```go-template
{{/*
Resolve module image: dev-workspace image when dev mode, else baked module image.
Usage: {{ include "druppie.moduleDevImage" (dict "root" . "image" .Values.modules.coding.image) }}
*/}}
{{- define "druppie.moduleDevImage" -}}
{{- if .root.Values.devWorkspace.enabled -}}
{{- printf "%s/%s:%s" .root.Values.global.imageRegistry .root.Values.devWorkspace.image.repository (.root.Values.devWorkspace.image.tag | default .root.Values.global.imageTag | default "latest") -}}
{{- else -}}
{{- include "druppie.image" . -}}
{{- end -}}
{{- end -}}
```

### 4. All 13 module Deployment templates

For each `templates/module-<key>-deployment.yaml`:

#### Line 1: Remove moduleEmbedded gate

```diff
- {{- if and .Values.modules.coding.enabled (not (include "druppie.moduleEmbedded" (dict "root" . "mod" "coding"))) }}
+ {{- if .Values.modules.coding.enabled }}
```

#### Container spec: Conditional dev-mode overrides

When in dev mode, override image, command, and mounts:

```yaml
      containers:
        - name: module-coding
          {{- if include "druppie.moduleDevMode" (dict "root" . "mod" "coding") }}
          # Dev mode: run from source on workspace PVC (hot-reload)
          image: {{ include "druppie.moduleDevImage" (dict "root" . "image" .Values.modules.coding.image) }}
          imagePullPolicy: Always
          command:
            - bash
            - /scripts/module-dev-entrypoint.sh
            - "coding"
            - "module-coding"
            - "9001"
          {{- else }}
          # Baked mode: production image
          image: {{ include "druppie.image" (dict "Values" .Values "image" .Values.modules.coding.image) }}
          imagePullPolicy: {{ .Values.global.imagePullPolicy }}
          {{- end }}
```

#### Volume mounts: Mount workspace PVC when dev mode

```yaml
          volumeMounts:
            {{- if include "druppie.moduleDevMode" (dict "root" . "mod" "coding") }}
            - name: workspace-dev
              mountPath: /workspace
            - name: module-dev-entrypoint
              mountPath: /scripts
              readOnly: true
            {{- else }}
            - name: workspace
              mountPath: /workspaces
            {{- end }}
            {{- if .Values.backend.dockerSocket.enabled }}
            - name: docker-sock
              mountPath: /var/run/docker.sock
            {{- end }}
```

#### Pod labels: Always add shared-storage label

```yaml
      metadata:
        labels:
          {{- include "druppie.selectorLabels" . | nindent 8 }}
          app.kubernetes.io/component: module-coding
          {{- if not .Values.persistence.rwx }}
          druppie.io/shared-storage: "true"
          {{- end }}
```

#### Pod spec: Add affinity + entrypoint volume

```yaml
    spec:
      {{- include "druppie.sharedStorageAffinity" . | nindent 6 }}
      # ... existing init containers, imagePullSecrets, etc ...
      volumes:
        {{- if include "druppie.moduleDevMode" (dict "root" . "mod" "coding") }}
        - name: workspace-dev
          persistentVolumeClaim:
            claimName: {{ include "druppie.fullname" . }}-workspace-dev
        - name: module-dev-entrypoint
          configMap:
            name: {{ include "druppie.fullname" . }}-module-dev-entrypoint
            defaultMode: 0755
        {{- else }}
        - name: workspace
          persistentVolumeClaim:
            claimName: {{ include "druppie.fullname" . }}-workspace
        {{- end }}
```

#### Liveness/readiness probes: Skip in dev mode (uvicorn --reload has no /health)

The baked images have a `/health` endpoint. The raw `uvicorn server:app` from
source does NOT (unless server.py defines one). Use TCP probe in dev mode:

```yaml
          {{- if include "druppie.moduleDevMode" (dict "root" . "mod" "coding") }}
          livenessProbe:
            tcpSocket:
              port: {{ .Values.modules.coding.port }}
            initialDelaySeconds: 15
            periodSeconds: 30
            failureThreshold: 5
          readinessProbe:
            tcpSocket:
              port: {{ .Values.modules.coding.port }}
            initialDelaySeconds: 5
            periodSeconds: 10
          {{- else }}
          livenessProbe:
            httpGet:
              path: /health
              port: {{ .Values.modules.coding.port }}
            # ... existing probe config ...
          readinessProbe:
            httpGet:
              path: /health
              port: {{ .Values.modules.coding.port }}
            # ... existing probe config ...
          {{- end }}
```

### 5. `services.yaml` — Remove selector flip

All module Services always target `module-<key>` / port `http`:

```diff
  selector:
    {{- include "druppie.selectorLabels" . | nindent 4 }}
-   app.kubernetes.io/component: {{ if include "druppie.moduleEmbedded" (dict "root" . "mod" "coding") }}dev-workspace{{ else }}module-coding{{ end }}
+   app.kubernetes.io/component: module-coding
  ports:
    - name: http
      port: {{ .Values.modules.coding.port }}
-     targetPort: {{ if include "druppie.moduleEmbedded" (dict "root" . "mod" "coding") }}mcp-coding{{ else }}http{{ end }}
+     targetPort: http
```

Apply this pattern to ALL 11 module Services in `services.yaml`.

### 6. Module Services in inline deployment files

`module-data-access-deployment.yaml` and `module-azuredevops-deployment.yaml`
have inline Services with the same flip logic. Remove the flip there too.

### 7. `dev-workspace-deployment.yaml` — Stop launching embedded modules

Set `EMBED_MODULES` to empty (modules now run as separate pods):

```diff
            - name: EMBED_MODULES
-             value: {{ join " " .Values.devWorkspace.embedModules | quote }}
+             value: ""
```

Remove the embedded module container ports (lines 148-157) since no modules
listen on the workspace pod anymore:

```diff
          ports:
            - { name: backend,     containerPort: 8000 }
            - { name: frontend,    containerPort: 5173 }
            - { name: code-server, containerPort: 8080 }
-           {{- range $key := .Values.devWorkspace.embedModules }}
-           {{- $mod := index $.Values.modules $key }}
-           {{- if $mod }}
-           - { name: mcp-{{ $key | replace "_" "-" }}, containerPort: {{ $mod.port }} }
-           {{- end }}
-           {{- end }}
```

The workspace pod keeps backend + frontend + code-server. Modules are now
external pods that the Services route to normally.

### 8. `configmap.yaml` — Fix sandbox namespace per-instance (already done on colab-dev)

Already fixed in previous work. Just ensure `SANDBOX_NAMESPACE` and
`SANDBOX_WARMPOOL` use `{{ .Values.global.instance }}` not hardcoded values.

### 9. `scripts/deploy-branch-env.sh` — Keep embedModules as-is

The `--set devWorkspace.embedModules={...}` stays. It now controls which
module pods run in dev mode (from source on PVC) vs baked image. The deploy
script already pins all module pods to the same node via
`modules.<key>.nodeSelector.kubernetes.io/hostname=${NODE}` (line 167-169),
which satisfies the RWO PVC co-location requirement.

## Module Catalog (for reference)

Must stay in sync across all sites:

| key | dir | port | needs docker.sock |
|-----|-----|------|-------------------|
| coding | module-coding | 9001 | yes |
| docker | module-docker | 9002 | yes |
| filesearch | module-filesearch | 9004 | no |
| web | module-web | 9005 | no |
| archimate | module-archimate | 9006 | no |
| registry | module-registry | 9007 | no |
| llm | module-llm | 9008 | no |
| kubernetes | module-kubernetes | 9013 | no |
| vision | module-vision | 9011 | GPU |
| searxng | module-searxng | 9014 | no |
| browser | module-browser | 9015 | no |
| data_access | module-data-access | 9010 | no |
| azuredevops | module-azuredevops | 9012 | no |

## Implementation Order

1. Create `scripts/module-dev-entrypoint.sh`
2. Create `helm/druppie/templates/_module-dev-configmap.yaml`
3. Update `_helpers.tpl` (rename helper, add moduleDevImage)
4. Update all 13 module deployment templates
5. Update `services.yaml` (remove selector flips)
6. Update inline Services in data-access + azuredevops deployments
7. Update `dev-workspace-deployment.yaml` (clear EMBED_MODULES, remove ports)
8. Push to `colab-dev`, test with a feature branch
9. Propagate to `main` + all feature branches

## Testing Checklist

After deploying to a feature branch:

- [ ] `kubectl get pods -n druppie-<branch>` — shows separate module pods (not just workspace)
- [ ] `kubectl get pods -n druppie-<branch> -l app.kubernetes.io/component=module-coding` — Running
- [ ] Module pods mount workspace PVC: `kubectl exec ... -- ls /workspace/druppie/mcp-servers/`
- [ ] Module pods run as root: `kubectl exec ... -- id` → uid=0
- [ ] Agent can read files (read_file tool works)
- [ ] Agent can push changes (push_changes tool works — no dubious ownership)
- [ ] Agent can use make_design
- [ ] Hot-reload works: edit a module file in code-server, module pod picks it up
- [ ] All module pods are on the same node: `kubectl get pods -o wide -l druppie.io/shared-storage=true`
- [ ] Backend/frontend still work (workspace pod still runs them)

## Rollback

If something breaks, set `devWorkspace.embedModules=[]` in the HelmRelease
values. All module pods fall back to baked images (no PVC mount, no dev mode).
The workspace pod won't launch modules (EMBED_MODULES="" always), so modules
run purely as separate baked-image pods — identical to colab-dev/main.
