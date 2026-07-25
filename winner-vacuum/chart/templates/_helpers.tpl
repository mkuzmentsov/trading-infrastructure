{{- define "polymarket-btc-5m-bot.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "polymarket-btc-5m-bot.labels" -}}
app.kubernetes.io/name: polymarket-btc-5m-bot
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "polymarket-btc-5m-bot.selectorLabels" -}}
app.kubernetes.io/name: polymarket-btc-5m-bot
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
