#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[auth-bridge] $*"
}

dump_helper_logs() {
  for file in /tmp/xvfb.log /tmp/fluxbox.log /tmp/x11vnc.log /tmp/websockify.log; do
    if [ -s "$file" ]; then
      log "---- ${file} ----"
      cat "$file" || true
      log "---- end ${file} ----"
    fi
  done
}

cleanup() {
  log "Stopping Auth Bridge services"
  kill "${NGINX_PID:-}" "${APP_PID:-}" "${WEBSOCKIFY_PID:-}" "${X11VNC_PID:-}" "${FLUXBOX_PID:-}" "${XVFB_PID:-}" 2>/dev/null || true
  rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
}

export DISPLAY=:99
export CHROMIUM_EXECUTABLE="${CHROMIUM_EXECUTABLE:-/usr/bin/chromium}"
export AUTH_BRIDGE_MODE="${AUTH_BRIDGE_MODE:-standalone}"
export AUTH_BRIDGE_PORT="${AUTH_BRIDGE_PORT:-8099}"

trap cleanup EXIT INT TERM

log "Starting Nest Protect Auth Bridge in ${AUTH_BRIDGE_MODE} mode"
log "Using Chromium executable: ${CHROMIUM_EXECUTABLE}"
log "Auth Bridge port: ${AUTH_BRIDGE_PORT}"
log "Cleaning stale Xvfb locks"
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
mkdir -p /tmp/.X11-unix

sed -i "s/listen 8099;/listen ${AUTH_BRIDGE_PORT};/" /etc/nginx/conf.d/default.conf

log "Starting Xvfb"
Xvfb :99 -screen 0 1280x800x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
sleep 1
if ! kill -0 "$XVFB_PID" 2>/dev/null; then
  log "Xvfb failed during startup"
  dump_helper_logs
  exit 1
fi

log "Starting helper services"
fluxbox >/tmp/fluxbox.log 2>&1 &
FLUXBOX_PID=$!

x11vnc -display :99 -rfbport 5900 -shared -forever -nopw -localhost >/tmp/x11vnc.log 2>&1 &
X11VNC_PID=$!

python -m websockify --web /usr/share/novnc/ 5901 localhost:5900 >/tmp/websockify.log 2>&1 &
WEBSOCKIFY_PID=$!

log "Starting Flask Auth Bridge app"
python /app/main.py &
APP_PID=$!

log "Starting nginx"
nginx -g 'daemon off;' &
NGINX_PID=$!

log "Startup complete; waiting for critical services"

set +e
wait -n "$NGINX_PID" "$APP_PID"
EXITED_STATUS=$?
set -e

if ! kill -0 "$NGINX_PID" 2>/dev/null; then
  log "Critical service exited: nginx"
elif ! kill -0 "$APP_PID" 2>/dev/null; then
  log "Critical service exited: Flask Auth Bridge app"
else
  log "A critical Auth Bridge service exited"
fi

dump_helper_logs
if [ "$EXITED_STATUS" -eq 0 ]; then
  exit 1
fi
exit "$EXITED_STATUS"
