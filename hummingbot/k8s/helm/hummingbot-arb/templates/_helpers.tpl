{{- define "hummingbot-arb.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "hummingbot-arb.labels" -}}
app.kubernetes.io/name: hummingbot-arb
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "hummingbot-arb.selectorLabels" -}}
app.kubernetes.io/name: hummingbot-arb
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
