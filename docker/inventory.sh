#!/usr/bin/env bash
# Run the inventory server in Docker, on your tailnet via a Tailscale sidecar.
#
#   docker/inventory.sh up [--printer [/dev/usb/lpN]] [--no-build]
#   docker/inventory.sh down | restart | logs [svc] | status | url | shell
#
# Reads (all optional except the auth key on first start):
#   ~/.config/inventory/tsauthkey    Tailscale auth key; only needed until the
#                                    node has joined (state is kept after that)
#   ~/.config/inventory/secrets.env  GOOGLE_VISION_API_KEY=, ANTHROPIC_API_KEY=, ...
#   ~/.config/inventory/printd.env   PRINTD_* overrides (see README "The printer")
#
# Environment overrides:
#   INVENTORY_HOME        data dir (default ~/.local/share/inventory): db,
#                         photos, CLIP model, tailscale node state
#   TS_HOSTNAME           tailnet name (default inventory)
#   TS_AUTHKEY_FILE       auth key path (default ~/.config/inventory/tsauthkey)
#   INVENTORY_LOCAL_PORT  host port for local access (default 8080)
#   INVENTORY_BIND        host address for it (default 127.0.0.1)
#   INVENTORY_PUBLIC_URL  pin label QR codes to this base URL
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/inventory"
export INVENTORY_HOME="${INVENTORY_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/inventory}"
export TS_HOSTNAME="${TS_HOSTNAME:-inventory}"
TS_AUTHKEY_FILE="${TS_AUTHKEY_FILE:-$CONF_DIR/tsauthkey}"

die() { echo "inventory: $*" >&2; exit 1; }

command -v docker >/dev/null || die "docker not found"
docker compose version >/dev/null 2>&1 || die "needs Docker Compose v2 ('docker compose')"

compose() { docker compose -f "$HERE/compose.yaml" "$@"; }

# Variables compose.yaml needs even for down/logs (it interpolates the whole file).
setup_env() {
  mkdir -p "$INVENTORY_HOME/data" "$INVENTORY_HOME/tailscale"
  export INVENTORY_UID INVENTORY_GID
  INVENTORY_UID="$(id -u)"
  INVENTORY_GID="$(id -g)"
  export INVENTORY_ENV_FILE=/dev/null PRINTD_ENV_FILE=/dev/null
  [[ -f "$CONF_DIR/secrets.env" ]] && INVENTORY_ENV_FILE="$CONF_DIR/secrets.env"
  [[ -f "$CONF_DIR/printd.env" ]] && PRINTD_ENV_FILE="$CONF_DIR/printd.env"
  export TS_AUTHKEY_MOUNT=/dev/null TS_AUTHKEY_ARG=""
  if [[ -s "$TS_AUTHKEY_FILE" ]]; then
    TS_AUTHKEY_MOUNT="$(cd "$(dirname "$TS_AUTHKEY_FILE")" && pwd)/$(basename "$TS_AUTHKEY_FILE")"
    TS_AUTHKEY_ARG="file:/run/secrets/tsauthkey"
  fi
}

joined() { [[ -n "$(ls -A "$INVENTORY_HOME/tailscale" 2>/dev/null)" ]]; }

# The node's MagicDNS name, once it's up; empty otherwise.
ts_name() {
  compose exec -T tailscale tailscale status --json --peers=false 2>/dev/null \
    | sed -n 's/.*"DNSName": *"\([^"]*\)\.".*/\1/p' | head -1 || true
}

cmd_up() {
  local build=1 printer=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --printer)
        if [[ "${2:-}" == /dev/* ]]; then printer="$2"; shift; else printer=auto; fi ;;
      --no-build) build=0 ;;
      *) die "up: unknown option $1" ;;
    esac
    shift
  done

  if [[ -z "$TS_AUTHKEY_ARG" ]] && ! joined; then
    die "no Tailscale auth key at $TS_AUTHKEY_FILE.
  Make one at https://login.tailscale.com/admin/settings/keys and save it there:
    mkdir -p $CONF_DIR && (umask 077; cat > $TS_AUTHKEY_FILE)   # paste, then Ctrl-D"
  fi
  if [[ -n "$TS_AUTHKEY_ARG" ]]; then
    [[ "$(stat -c %a "$TS_AUTHKEY_FILE" 2>/dev/null || stat -f %Lp "$TS_AUTHKEY_FILE")" =~ ^[0-7]00$ ]] \
      || echo "inventory: warning: $TS_AUTHKEY_FILE is readable by others (chmod 600 it)" >&2
  fi

  # The printer agent only runs if there's a USB printer to give it.
  if [[ "$printer" == auto ]]; then
    printer="$(ls /dev/usb/lp* 2>/dev/null | head -1 || true)"
    [[ -n "$printer" ]] || die "--printer: no /dev/usb/lp* on this host (is the printer plugged in?)"
  fi
  if [[ -n "$printer" ]]; then
    [[ -e "$printer" ]] || die "--printer: $printer does not exist"
    export COMPOSE_PROFILES=printer PRINTD_DEVICE="$printer"
    echo "inventory: printing to $printer"
  fi

  local args=(up -d --remove-orphans)
  ((build)) && args+=(--build)
  compose "${args[@]}"

  echo -n "inventory: waiting for the tailnet"
  local name="" i
  for i in $(seq 60); do
    name="$(ts_name)"
    [[ -n "$name" ]] && break
    echo -n .
    sleep 2
  done
  echo
  if [[ -z "$name" ]]; then
    echo "inventory: the node hasn't joined the tailnet yet. Check: $0 logs tailscale" >&2
    echo "inventory: meanwhile it's at http://${INVENTORY_BIND:-127.0.0.1}:${INVENTORY_LOCAL_PORT:-8080}" >&2
    exit 1
  fi
  echo "inventory: https://$name"
  echo "  (HTTPS needs MagicDNS + HTTPS certificates enabled for the tailnet:"
  echo "   https://login.tailscale.com/admin/dns ; the first request takes a few"
  echo "   seconds while the certificate is issued)"
  echo "inventory: also http://${INVENTORY_BIND:-127.0.0.1}:${INVENTORY_LOCAL_PORT:-8080} on this machine"
}

setup_env
case "${1:-}" in
  up) shift; cmd_up "$@" ;;
  down) compose --profile printer down ;;
  restart) compose --profile printer restart ;;
  logs) shift; compose --profile printer logs -f --tail=200 "$@" ;;
  status) compose --profile printer ps; name="$(ts_name)"; if [[ -n "$name" ]]; then echo "tailnet: https://$name"; fi ;;
  url) name="$(ts_name)"; [[ -n "$name" ]] || die "not on the tailnet (is it up?)"; echo "https://$name" ;;
  shell) compose exec server bash ;;
  *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
