#!/usr/bin/env bash
# Run the inventory server in Docker, on your tailnet via a Tailscale sidecar.
#
#   docker/inventory.sh up [--printd <tailnet host> | --printer [/dev/usb/lpN]] [--no-build]
#   docker/inventory.sh down | restart | logs [svc] | status | url | shell | backup [file]
#
# Reads (all optional except the auth key on first start):
#   ~/.config/inventory/tsauthkey    Tailscale auth key; only needed until the
#                                    node has joined (state is kept after that)
#   ~/.config/inventory/secrets.env  GOOGLE_VISION_API_KEY=, ANTHROPIC_API_KEY=, ...
#   ~/.config/inventory/printd.env   PRINTD_* overrides (see README "The printer")
#   ~/.config/inventory/docker.env   the environment overrides below, as VAR=value lines
#
# Environment overrides:
#   TS_HOSTNAME           tailnet name (default inventory)
#   TS_AUTHKEY_FILE       auth key path (default ~/.config/inventory/tsauthkey)
#   INVENTORY_LOCAL_PORT  host port for local access (default 8080)
#   INVENTORY_BIND        host address for it (default 127.0.0.1)
#   INVENTORY_PUBLIC_URL  pin label QR codes to this base URL
#   INVENTORY_PRINTD_HOST print via printd on this tailnet machine (= --printd)
#   INVENTORY_PRINTD_URL  or give printd's URL directly (use a tailnet IP:
#                         MagicDNS names don't resolve inside the containers)
#
# Data lives in Docker volumes (inventory_data, inventory_tailscale), not host
# folders. `backup` writes a .tar.gz of the data volume.
#
# --printd <host>: print through the printd on another tailnet machine (e.g.
# the Pi). Remembered in ~/.config/inventory/printd-host; `--printd local`
# forgets it.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/inventory"
if [[ -f "$CONF_DIR/docker.env" ]]; then
  set -a; . "$CONF_DIR/docker.env"; set +a
fi
export TS_HOSTNAME="${TS_HOSTNAME:-inventory}"
TS_AUTHKEY_FILE="${TS_AUTHKEY_FILE:-$CONF_DIR/tsauthkey}"
REMEMBERED_PRINTD="$CONF_DIR/printd-host"
LOCAL_URL="http://${INVENTORY_BIND:-127.0.0.1}:${INVENTORY_LOCAL_PORT:-8080}"

die() { echo "inventory: $*" >&2; exit 1; }

command -v docker >/dev/null || die "docker not found"
docker compose version >/dev/null 2>&1 || die "needs Docker Compose v2 ('docker compose')"

compose() { docker compose -f "$HERE/compose.yaml" "$@"; }

# env_file paths are read by the compose CLI on this machine, so they work
# even when the Docker daemon runs in a VM that can't see your home folder.
export INVENTORY_ENV_FILE=/dev/null PRINTD_ENV_FILE=/dev/null
[[ -f "$CONF_DIR/secrets.env" ]] && INVENTORY_ENV_FILE="$CONF_DIR/secrets.env"
[[ -f "$CONF_DIR/printd.env" ]] && PRINTD_ENV_FILE="$CONF_DIR/printd.env"

# The node's MagicDNS name, once it's up; empty otherwise.
ts_name() {
  compose exec -T tailscale tailscale status --json --peers=false 2>/dev/null \
    | sed -n 's/.*"DNSName": *"\([^"]*\)\.".*/\1/p' | head -1 || true
}

ts_state() { compose ps -a --format '{{.State}}' tailscale 2>/dev/null | head -1 || true; }

# Point the server at printd on a tailnet peer. By IP: the sidecar doesn't
# take over the containers' DNS, so MagicDNS names don't resolve in them.
use_remote_printd() {
  local host="$1" ip
  ip="$(compose exec -T tailscale tailscale ip -4 "$host" 2>/dev/null | head -1 || true)"
  [[ -n "$ip" ]] || die "--printd: no tailnet peer '$host' (check: tailscale status)"
  mkdir -p "$CONF_DIR"
  printf '%s\n' "$host" > "$REMEMBERED_PRINTD"
  export INVENTORY_PRINTD_URL="http://$ip:8631"
  compose up -d server >/dev/null 2>&1   # recreate with the new URL
  if compose exec -T server python -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1] + '/status', timeout=5)" \
       "$INVENTORY_PRINTD_URL" >/dev/null 2>&1; then
    echo "inventory: printing via printd on $host ($ip)"
  else
    echo "inventory: warning: printd on $host ($INVENTORY_PRINTD_URL) isn't answering." >&2
    echo "  Is the inventory system deployed there, with printd listening beyond localhost?" >&2
  fi
}

cmd_up() {
  local build=1 printer="" printd_host=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --printer)
        if [[ "${2:-}" == /dev/* ]]; then printer="$2"; shift; else printer=auto; fi ;;
      --printd) printd_host="${2:?--printd needs a tailnet host}"; shift ;;
      --no-build) build=0 ;;
      *) die "up: unknown option $1" ;;
    esac
    shift
  done

  # The key goes to the container as an environment variable, not a mounted
  # file. Only the first start needs it; after that the node state is kept.
  if [[ -s "$TS_AUTHKEY_FILE" ]]; then
    [[ "$(stat -c %a "$TS_AUTHKEY_FILE" 2>/dev/null || stat -f %Lp "$TS_AUTHKEY_FILE")" =~ ^[0-7]00$ ]] \
      || echo "inventory: warning: $TS_AUTHKEY_FILE is readable by others (chmod 600 it)" >&2
    TS_AUTHKEY="$(tr -d '[:space:]' < "$TS_AUTHKEY_FILE")"
    export TS_AUTHKEY
  elif ! docker volume inspect inventory_tailscale >/dev/null 2>&1; then
    die "no Tailscale auth key at $TS_AUTHKEY_FILE.
  Make one at https://login.tailscale.com/admin/settings/keys and save it there:
    mkdir -p $CONF_DIR && (umask 077; cat > $TS_AUTHKEY_FILE)   # paste, then Ctrl-D"
  fi

  # Which printd: --printd, else INVENTORY_PRINTD_HOST, else the last
  # --printd, else INVENTORY_PRINTD_URL as given, else the local one.
  if [[ "$printd_host" == local ]]; then
    rm -f "$REMEMBERED_PRINTD"; printd_host=""
  elif [[ -z "$printd_host" && -n "${INVENTORY_PRINTD_HOST:-}" ]]; then
    printd_host="$INVENTORY_PRINTD_HOST"
  elif [[ -z "$printd_host" && -s "$REMEMBERED_PRINTD" ]]; then
    printd_host="$(cat "$REMEMBERED_PRINTD")"
  fi
  [[ -n "$printd_host" && -n "$printer" ]] && die "use either --printd or --printer, not both"

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
    # A crash-looping sidecar won't recover by waiting; show why.
    if ((i > 3)) && [[ "$(ts_state)" == restarting ]]; then
      echo
      compose logs --tail=15 tailscale >&2
      die "the tailscale container keeps restarting (log above)"
    fi
    echo -n .
    sleep 2
  done
  echo
  if [[ -z "$name" ]]; then
    compose logs --tail=15 tailscale >&2
    echo "inventory: the node hasn't joined the tailnet yet (log above). More: $0 logs tailscale" >&2
    echo "inventory: meanwhile it's at $LOCAL_URL" >&2
    exit 1
  fi
  [[ -n "$printd_host" ]] && use_remote_printd "$printd_host"
  echo "inventory: https://$name"
  echo "  (HTTPS needs MagicDNS + HTTPS certificates enabled for the tailnet:"
  echo "   https://login.tailscale.com/admin/dns ; the first request takes a few"
  echo "   seconds while the certificate is issued)"
  echo "inventory: also $LOCAL_URL on this machine"
}

cmd_backup() {
  local out="${1:-inventory-backup-$(date +%Y%m%d-%H%M%S).tar.gz}"
  compose exec -T server tar czf - -C /data --exclude=./models . > "$out"
  echo "inventory: wrote $out (database + photos; the CLIP model re-downloads)"
}

case "${1:-}" in
  up) shift; cmd_up "$@" ;;
  down) compose --profile printer down ;;
  restart) compose --profile printer restart ;;
  logs) shift; compose --profile printer logs -f --tail=200 "$@" ;;
  status) compose --profile printer ps; name="$(ts_name)"; if [[ -n "$name" ]]; then echo "tailnet: https://$name"; fi ;;
  url) name="$(ts_name)"; [[ -n "$name" ]] || die "not on the tailnet (is it up?)"; echo "https://$name" ;;
  shell) compose exec server bash ;;
  backup) shift; cmd_backup "$@" ;;
  *) sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
