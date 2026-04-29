{{- $modelFiles := .Files.Glob "files/model/*" -}}
{{- if $modelFiles }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "polymarket-btc-bot.name" . }}-model
  labels:
    {{- include "polymarket-btc-bot.labels" . | nindent 4 }}
binaryData:
  {{- range $path, $_ := $modelFiles }}
  {{ base $path }}: {{ $.Files.Get $path | b64enc }}
  {{- end }}
{{- end }}
