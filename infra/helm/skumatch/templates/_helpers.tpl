{{- define "skumatch.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "skumatch.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "skumatch.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "skumatch.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
app.kubernetes.io/name: {{ include "skumatch.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "skumatch.selectorLabels" -}}
app.kubernetes.io/name: {{ include "skumatch.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "skumatch.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{- define "skumatch.dbSecretName" -}}
{{- default (printf "%s-db" (include "skumatch.fullname" .)) .Values.database.existingSecret -}}
{{- end -}}

{{- define "skumatch.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "skumatch.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Env vars that assemble SQLAlchemy URLs from the DB secret at runtime (no URL in values). */}}
{{- define "skumatch.dbEnv" -}}
- name: DB_USER
  valueFrom:
    secretKeyRef:
      name: {{ include "skumatch.dbSecretName" . }}
      key: username
- name: DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "skumatch.dbSecretName" . }}
      key: password
{{- end -}}
