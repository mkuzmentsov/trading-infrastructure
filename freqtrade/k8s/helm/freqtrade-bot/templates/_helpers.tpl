{{- define "freqtrade-bot.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "freqtrade-bot.labels" -}}
app.kubernetes.io/name: freqtrade-bot
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "freqtrade-bot.selectorLabels" -}}
app.kubernetes.io/name: freqtrade-bot
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
