{{- define "polymarket-btc-15m-bot.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "polymarket-btc-15m-bot.labels" -}}
app.kubernetes.io/name: polymarket-btc-15m-bot
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "polymarket-btc-15m-bot.selectorLabels" -}}
app.kubernetes.io/name: polymarket-btc-15m-bot
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
