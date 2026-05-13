{{- define "funding-carry-bot.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "funding-carry-bot.labels" -}}
app.kubernetes.io/name: funding-carry-bot
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "funding-carry-bot.selectorLabels" -}}
app.kubernetes.io/name: funding-carry-bot
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
