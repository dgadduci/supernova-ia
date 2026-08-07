FROM tailscale/tailscale:v1.98.9 AS tailscale

FROM python:3.13-slim

WORKDIR /app

COPY --from=tailscale /usr/local/bin/tailscale /usr/local/bin/tailscale
COPY --from=tailscale /usr/local/bin/tailscaled /usr/local/bin/tailscaled
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod 755 docker-entrypoint.sh

CMD ["./docker-entrypoint.sh"]
