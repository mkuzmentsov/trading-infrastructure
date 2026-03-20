{{- define "coturn.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "coturn.labels" -}}
app.kubernetes.io/name: coturn
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "coturn.selectorLabels" -}}
app.kubernetes.io/name: coturn
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
