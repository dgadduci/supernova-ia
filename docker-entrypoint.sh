#!/bin/sh
set -eu

required_var() {
    value=$(printenv "$1" || true)
    if [ -z "$value" ]; then
        echo "startup_error missing_required_variable=$1" >&2
        exit 1
    fi
}

required_var SUPERNOVA_DATABASE_URL
required_var TS_AUTHKEY
required_var TS_HOSTNAME
required_var OLLAMA_PROXY_URL
required_var PORT

provider_worker_enabled=0
case "${PROVIDER_PROCESSING_WORKER_ENABLED-false}" in
    1|true|TRUE|yes|YES|on|ON)
        provider_worker_enabled=1
        ;;
    0|false|FALSE|no|NO|off|OFF)
        provider_worker_enabled=0
        ;;
    *)
        echo "startup_error provider_worker_invalid_flag" >&2
        exit 1
        ;;
esac

socket_path=/tmp/tailscaled.sock
ready_timeout_seconds=${TS_READY_TIMEOUT_SECONDS:-30}

case "$ready_timeout_seconds" in
    *[!0-9]* | '')
        echo "startup_error invalid_ts_ready_timeout_seconds" >&2
        exit 1
        ;;
esac

echo "migration=starting"
if ! python -m alembic upgrade head; then
    echo "startup_error migration_failed" >&2
    exit 1
fi
echo "migration=completed"

tailscaled \
    --tun=userspace-networking \
    --state=mem: \
    --socket="$socket_path" \
    --socks5-server=127.0.0.1:1055 \
    --outbound-http-proxy-listen=127.0.0.1:1056 &
tailscaled_pid=$!

stop_processes() {
    kill "$tailscaled_pid" 2>/dev/null || true
    if [ "${worker_pid:-}" ]; then
        kill "$worker_pid" 2>/dev/null || true
    fi
    if [ "${app_pid:-}" ]; then
        kill "$app_pid" 2>/dev/null || true
    fi
}
trap stop_processes INT TERM

if [ "$provider_worker_enabled" = "1" ]; then
    echo "provider_worker=enabled validating_configuration"
    if ! python -c 'from backend.cli.run_provider_processing_worker import validate_worker_startup_or_exit; validate_worker_startup_or_exit()'; then
        echo "startup_error provider_worker_configuration_invalid" >&2
        exit 1
    fi
    echo "provider_worker=configuration_validated"
fi

if ! tailscale --socket="$socket_path" up --auth-key="$TS_AUTHKEY" --hostname="$TS_HOSTNAME"; then
    echo "startup_error tailscale_authentication_failed" >&2
    exit 1
fi

deadline=$(( $(date +%s) + ready_timeout_seconds ))
while :; do
    if ! kill -0 "$tailscaled_pid" 2>/dev/null; then
        echo "startup_error tailscaled_exited_before_ready" >&2
        exit 1
    fi
    if tailscale --socket="$socket_path" status --json 2>/dev/null | python -c 'import json, sys; raise SystemExit(0 if json.load(sys.stdin).get("BackendState") == "Running" else 1)'; then
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "startup_error tailscale_not_ready" >&2
        exit 1
    fi
    sleep 1
done

echo "tailscale_ready proxy=enabled"
uvicorn backend.main:app --host 0.0.0.0 --port "$PORT" &
app_pid=$!

if [ "$provider_worker_enabled" = "1" ]; then
    python -m backend.cli.run_provider_processing_worker &
    worker_pid=$!
    echo "provider_worker_started pid=$worker_pid"
fi

while kill -0 "$app_pid" 2>/dev/null; do
    if [ "$provider_worker_enabled" = "1" ] && ! kill -0 "${worker_pid:-0}" 2>/dev/null; then
        echo "startup_error provider_worker_exited" >&2
        kill "$app_pid" 2>/dev/null || true
        wait "$app_pid" 2>/dev/null || true
        exit 1
    fi
    if ! kill -0 "$tailscaled_pid" 2>/dev/null; then
        echo "startup_error tailscaled_exited" >&2
        kill "$app_pid" 2>/dev/null || true
        wait "$app_pid" 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

wait "$app_pid"
