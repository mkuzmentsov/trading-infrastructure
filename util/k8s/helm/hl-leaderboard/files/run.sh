#!/bin/bash
set -euo pipefail

OUTFILE=$(mktemp /tmp/leaderboard-XXXXXX.txt)
python3 /app/hl_leaderboard.py $LEADERBOARD_ARGS --wallets-file /app/wallets-of-interest.txt 2>&1 | tee "$OUTFILE"
EXIT_CODE=${PIPESTATUS[0]}

if [ -n "${TELEGRAM_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
  OUTFILE="$OUTFILE" \
  CAPTION="HL Leaderboard — $(date -u '+%Y-%m-%d %H:%M UTC')" \
  python3 - <<'EOF'
import os, urllib.request
from datetime import datetime, timezone

token   = os.environ['TELEGRAM_TOKEN']
chat_id = os.environ['TELEGRAM_CHAT_ID']
caption = os.environ['CAPTION']
outfile = os.environ['OUTFILE']

with open(outfile, 'rb') as f:
    file_data = f.read()

filename  = datetime.now(timezone.utc).strftime('%d-%m-%Y-%H-%M') + '.txt'
boundary  = b'----Boundary7a3f9e1d'

body = (
    b'--' + boundary + b'\r\n'
    b'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
    + chat_id.encode() + b'\r\n'
    + b'--' + boundary + b'\r\n'
    b'Content-Disposition: form-data; name="caption"\r\n\r\n'
    + caption.encode() + b'\r\n'
    + b'--' + boundary + b'\r\n'
    + f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode()
    b'Content-Type: text/plain\r\n\r\n'
    + file_data + b'\r\n'
    + b'--' + boundary + b'--\r\n'
)

req = urllib.request.Request(
    f'https://api.telegram.org/bot{token}/sendDocument',
    data=body,
    headers={'Content-Type': f'multipart/form-data; boundary={boundary.decode()}'},
)
urllib.request.urlopen(req)
EOF
fi

rm -f "$OUTFILE"
exit $EXIT_CODE
