{{- define "polymarket-bot.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "polymarket-bot.labels" -}}
app.kubernetes.io/name: polymarket-bot
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "polymarket-bot.selectorLabels" -}}
app.kubernetes.io/name: polymarket-bot
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
