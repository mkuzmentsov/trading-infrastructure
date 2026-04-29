{{- define "polymarket-btc-bot.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "polymarket-btc-bot.labels" -}}
app.kubernetes.io/name: polymarket-btc-bot
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "polymarket-btc-bot.selectorLabels" -}}
app.kubernetes.io/name: polymarket-btc-bot
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
