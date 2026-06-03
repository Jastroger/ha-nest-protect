ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}

WORKDIR /app

RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-virtualenv \
    chromium \
    nss \
    freetype \
    harfbuzz \
    ttf-freefont \
    xvfb \
    x11vnc \
    fluxbox \
    novnc \
    nginx

COPY app/requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY app /app
COPY run.sh /run.sh
COPY nginx.conf /etc/nginx/http.d/default.conf
RUN chmod +x /run.sh

ENV PATH="/opt/venv/bin:${PATH}"
ENV PYTHONUNBUFFERED=1
ENV AUTH_BRIDGE_MODE=addon
ENV AUTH_BRIDGE_PORT=8099

EXPOSE 8099

CMD ["/run.sh"]
