{{- define "pattern-bot.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "pattern-bot.labels" -}}
app.kubernetes.io/name: pattern-bot
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "pattern-bot.selectorLabels" -}}
app.kubernetes.io/name: pattern-bot
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
