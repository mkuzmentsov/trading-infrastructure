{{- define "polymarket-portfolio-bot.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "polymarket-portfolio-bot.labels" -}}
app.kubernetes.io/name: polymarket-portfolio-bot
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "polymarket-portfolio-bot.selectorLabels" -}}
app.kubernetes.io/name: polymarket-portfolio-bot
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
