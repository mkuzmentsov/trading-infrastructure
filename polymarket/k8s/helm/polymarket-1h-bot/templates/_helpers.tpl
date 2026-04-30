{{- define "polymarket-1h-bot.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "polymarket-1h-bot.labels" -}}
app.kubernetes.io/name: polymarket-1h-bot
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "polymarket-1h-bot.selectorLabels" -}}
app.kubernetes.io/name: polymarket-1h-bot
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
