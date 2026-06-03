#!/usr/bin/with-contenv bashio
set -euo pipefail

export DISPLAY=:99
export CHROMIUM_EXECUTABLE="${CHROMIUM_EXECUTABLE:-/usr/bin/chromium-browser}"
export AUTH_BRIDGE_MODE="${AUTH_BRIDGE_MODE:-addon}"
export AUTH_BRIDGE_PORT="${AUTH_BRIDGE_PORT:-8099}"

sed -i "s/listen 8099;/listen ${AUTH_BRIDGE_PORT};/" /etc/nginx/http.d/default.conf

Xvfb :99 -screen 0 1280x800x24 -nolisten tcp &
XVFB_PID=$!

fluxbox >/tmp/fluxbox.log 2>&1 &
FLUXBOX_PID=$!

x11vnc -display :99 -rfbport 5900 -shared -forever -nopw -localhost >/tmp/x11vnc.log 2>&1 &
X11VNC_PID=$!

python3 -m websockify --web /usr/share/novnc/ 5901 localhost:5900 >/tmp/websockify.log 2>&1 &
WEBSOCKIFY_PID=$!

python3 /app/main.py >/tmp/auth-bridge.log 2>&1 &
APP_PID=$!

nginx -g 'daemon off;' &
NGINX_PID=$!

trap "kill $NGINX_PID $APP_PID $WEBSOCKIFY_PID $X11VNC_PID $FLUXBOX_PID $XVFB_PID 2>/dev/null || true" EXIT

wait -n "$NGINX_PID" "$APP_PID" "$WEBSOCKIFY_PID" "$X11VNC_PID" "$FLUXBOX_PID" "$XVFB_PID"
