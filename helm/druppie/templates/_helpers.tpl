{{/*
Expand the name of the chart.
*/}}
{{- define "druppie.name" -}}
{{- default .Chart.Name .Values.global.instance | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "druppie.fullname" -}}
{{- if .Values.global.instance }}
{{- .Values.global.instance | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.global.instance }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "druppie.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "druppie.labels" -}}
helm.sh/chart: {{ include "druppie.chart" . }}
{{ include "druppie.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "druppie.selectorLabels" -}}
app.kubernetes.io/name: {{ include "druppie.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Service name helper
*/}}
{{- define "druppie.serviceName" -}}
{{- printf "%s" (include "druppie.fullname" .) }}
{{- end }}

{{/*
Image helper: renders a full image reference from registry + repository + tag
Usage: {{ include "druppie.image" (dict "Values" .Values "image" .Values.backend.image) }}
*/}}
{{- define "druppie.image" -}}
{{- $registry := .Values.global.imageRegistry -}}
{{- $repo := .image.repository -}}
{{- $tag := .Values.global.imageTag | default (.image.tag | default "latest") -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $repo $tag -}}
{{- else -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end -}}

{{/*
External scheme: http or https based on TLS enabled
*/}}
{{- define "druppie.scheme" -}}
{{- if .Values.global.ingress.tls.enabled -}}
https
{{- else -}}
http
{{- end -}}
{{- end -}}

{{/*
External base URL: scheme://domain(:port if non-standard)
- TLS enabled → https://domain (standard 443, no port)
- TLS disabled, port 80 → http://domain (standard 80, no port)
- TLS disabled, non-standard port → http://domain:port
*/}}
{{- define "druppie.externalBaseUrl" -}}
{{- $scheme := include "druppie.scheme" . -}}
{{- $domain := .Values.global.domain -}}
{{- $port := .Values.global.ingress.port | int -}}
{{- $tlsEnabled := .Values.global.ingress.tls.enabled -}}
{{- if $tlsEnabled -}}
{{- printf "%s://%s" $scheme $domain -}}
{{- else if eq $port 80 -}}
{{- printf "%s://%s" $scheme $domain -}}
{{- else -}}
{{- printf "%s://%s:%d" $scheme $domain $port -}}
{{- end -}}
{{- end -}}

{{/*
Backend external URL: ingress path or direct NodePort
*/}}
{{- define "druppie.backendExternalUrl" -}}
{{- if .Values.global.ingress.enabled -}}
{{ include "druppie.externalBaseUrl" . }}
{{- else -}}
http://{{ .Values.global.domain }}:{{ .Values.backend.nodePort }}
{{- end -}}
{{- end -}}

{{/*
Keycloak external URL
*/}}
{{- define "druppie.keycloakExternalUrl" -}}
{{- if .Values.global.ingress.enabled -}}
{{- if .Values.global.subdomains.keycloak -}}
{{ include "druppie.scheme" . }}://{{ .Values.global.subdomains.keycloak }}
{{- else -}}
{{ include "druppie.externalBaseUrl" . }}
{{- end -}}
{{- else -}}
http://{{ .Values.global.domain }}:{{ .Values.keycloak.nodePort }}
{{- end -}}
{{- end -}}

{{/*
Gitea external URL
*/}}
{{- define "druppie.giteaExternalUrl" -}}
{{- if .Values.global.ingress.enabled -}}
{{- if .Values.global.subdomains.gitea -}}
{{ include "druppie.scheme" . }}://{{ .Values.global.subdomains.gitea }}
{{- else -}}
{{ include "druppie.externalBaseUrl" . }}/git
{{- end -}}
{{- else -}}
http://{{ .Values.global.domain }}:{{ .Values.gitea.nodePort }}
{{- end -}}
{{- end -}}

{{/*
Frontend external URL
*/}}
{{- define "druppie.frontendExternalUrl" -}}
{{- if .Values.global.ingress.enabled -}}
{{ include "druppie.externalBaseUrl" . }}
{{- else -}}
http://{{ .Values.global.domain }}:{{ .Values.frontend.nodePort }}
{{- end -}}
{{- end -}}

{{/*
Shared-storage affinity block for pod spec.
Renders nothing when persistence.rwx is true (RWX allows multi-node access).
When RWO, co-locates all pods carrying the druppie.io/shared-storage label
on the same node so they can share ReadWriteOnce PVCs (workspace, dataset).
*/}}
{{- define "druppie.sharedStorageAffinity" -}}
{{- if not .Values.persistence.rwx }}
affinity:
  podAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            {{- include "druppie.selectorLabels" . | nindent 12 }}
            druppie.io/shared-storage: "true"
        topologyKey: kubernetes.io/hostname
{{- end }}
{{- end }}

{{/*
Persistence storageClass: resolves to NFS class when NFS is enabled,
otherwise falls back to the configured persistence.storageClass.
*/}}
{{- define "druppie.persistence.storageClass" -}}
{{- if .Values.nfs.enabled -}}
{{ .Values.nfs.storageClassName }}
{{- else if .Values.persistence.storageClass -}}
{{ .Values.persistence.storageClass }}
{{- end -}}
{{- end -}}

{{/*
Module-embedded predicate: returns the string "true" (empty otherwise) when
devWorkspace is enabled AND the given module key (arg `mod`) appears in
devWorkspace.embedModules — i.e. that module should run inside the workspace
pod under uvicorn --reload instead of as its own baked-image Deployment.

Returns "true" / "" (not a raw bool) so it composes correctly under `{{ if }}`:
Go-template `if` treats every non-empty string — including "false" — as truthy,
so a boolean-returning helper would always read as true at the call site.

Usage: {{ $emb := include "druppie.moduleEmbedded" (dict "root" . "mod" "coding") }}
       {{- if $emb }} ... {{- end }}
*/}}
{{- define "druppie.moduleEmbedded" -}}
{{- if and .root.Values.devWorkspace.enabled (has .mod .root.Values.devWorkspace.embedModules) -}}true{{- end -}}
{{- end -}}

{{/*
ESO dockerconfigjson template string for harbor-regcred ExternalSecret.
Outputs the literal ESO template (with {{ .username }} etc.) without Helm
interpreting the inner {{ }} as Helm expressions.
*/}}
{{- define "druppie.eso-dockerconfigjson" -}}
{"auths":{"{{ "{{" }} .registry {{ "}}" }}":{"username":"{{ "{{" }} .username {{ "}}" }}","password":"{{ "{{" }} .password {{ "}}" }}","auth":"{{ "{{" }} printf "%s:%s" .username .password | b64enc {{ "}}" }}"}}}
{{- end -}}
