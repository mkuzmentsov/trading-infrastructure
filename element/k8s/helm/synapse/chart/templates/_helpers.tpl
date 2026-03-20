{{- define "synapse.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "synapse.labels" -}}
app.kubernetes.io/name: synapse
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "synapse.selectorLabels" -}}
app.kubernetes.io/name: synapse
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
