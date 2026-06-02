ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}

WORKDIR /app

RUN apk add --no-cache \
    python3 \
    py3-pip \
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
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY app /app
COPY run.sh /run.sh
COPY nginx.conf /etc/nginx/http.d/default.conf
RUN chmod +x /run.sh

ENV PYTHONUNBUFFERED=1

CMD ["/run.sh"]
