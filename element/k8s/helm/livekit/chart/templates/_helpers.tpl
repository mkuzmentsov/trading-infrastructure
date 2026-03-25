{{- define "livekit.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "livekit.labels" -}}
app.kubernetes.io/name: livekit
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "livekit.selectorLabels" -}}
app.kubernetes.io/name: livekit
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
