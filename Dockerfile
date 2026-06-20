FROM alpine:latest

LABEL maintainer="Alireza.Msh"
LABEL version="1.1.1"
LABEL description="WireGuard Peer Management Panel for MikroTik"

RUN apk add --no-cache \
    python3 \
    py3-pip \
    wireguard-tools \
    libqrencode-tools \
    tzdata \
    && pip install --break-system-packages \
        flask \
        routeros-api \
        "qrcode[pil]" \
        pillow

WORKDIR /app
COPY wgpanel/ .

RUN mkdir -p /data

VOLUME ["/data"]
EXPOSE 5050

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Tehran \
    DB_PATH=/data/wgpanel.db

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget -qO- http://localhost:5050/login > /dev/null || exit 1

CMD ["python3", "app.py"]
