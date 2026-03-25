{{- define "lk-jwt-service.name" -}}
{{- .Release.Name | lower | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "lk-jwt-service.labels" -}}
app.kubernetes.io/name: lk-jwt-service
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "lk-jwt-service.selectorLabels" -}}
app.kubernetes.io/name: lk-jwt-service
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
