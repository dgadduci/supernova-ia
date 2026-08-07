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

socket_path=/tmp/tailscaled.sock
ready_timeout_seconds=${TS_READY_TIMEOUT_SECONDS:-30}

case "$ready_timeout_seconds" in
    *[!0-9]* | '')
        echo "startup_error invalid_ts_ready_timeout_seconds" >&2
        exit 1
        ;;
esac

tailscaled \
    --tun=userspace-networking \
    --state=mem: \
    --socket="$socket_path" \
    --socks5-server=127.0.0.1:1055 &
tailscaled_pid=$!

stop_processes() {
    kill "$tailscaled_pid" 2>/dev/null || true
    if [ "${app_pid:-}" ]; then
        kill "$app_pid" 2>/dev/null || true
    fi
}
trap stop_processes INT TERM

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
    if tailscale --socket="$socket_path" status --json 2>/dev/null | python -c 'import json, sys; raise SystemExit(0 if json.load(sys.stdin).get("BackendState") == "Running" else 1)' \
        && python -c 'import socket; connection = socket.create_connection(("127.0.0.1", 1055), 1); connection.sendall(b"\x05\x01\x00"); response = connection.recv(2); connection.close(); raise SystemExit(0 if response == b"\x05\x00" else 1)' 2>/dev/null; then
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

while kill -0 "$app_pid" 2>/dev/null; do
    if ! kill -0 "$tailscaled_pid" 2>/dev/null; then
        echo "startup_error tailscaled_exited" >&2
        kill "$app_pid" 2>/dev/null || true
        wait "$app_pid" 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

wait "$app_pid"
