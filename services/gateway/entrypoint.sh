#!/bin/sh
set -eu
printf '%b\n' "$GATEWAY_HTPASSWD" > /tmp/htpasswd
exec /docker-entrypoint.sh nginx -g 'daemon off;'
