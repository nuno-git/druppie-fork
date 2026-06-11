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
{{- $tag := .image.tag | default "latest" -}}
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
