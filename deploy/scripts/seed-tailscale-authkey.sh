#!/usr/bin/env bash
# Put the Tailscale auth key on the Pi and join the tailnet. tailscaled reads it
# from /var/lib/tailscale/authkey (services.tailscale.authKeyFile, see
# deploy/nix/system.nix). Run once after flashing a card: a reflash wipes
# /var/lib, a redeploy doesn't.
#
#   bazel run //deploy:seed_tailscale_authkey [-- host]      # default garage.local
#
# The key comes from TS_AUTHKEY_FILE, else deploy/secrets/tailscale-authkey,
# else ~/.config/inventory/tsauthkey (the same key the Docker setup uses).
# Mint one at https://login.tailscale.com/admin/settings/keys.
set -euo pipefail

HOST="${1:-garage.local}"
# Under `bazel run`, secrets live in the operator's checkout.
WS="${BUILD_WORKSPACE_DIRECTORY:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SECRETS="$WS/deploy/secrets"
DEPLOY_KEY="$SECRETS/deploy_key"

KEY="${TS_AUTHKEY_FILE:-}"
if [[ -z "$KEY" ]]; then
  for k in "$SECRETS/tailscale-authkey" "${XDG_CONFIG_HOME:-$HOME/.config}/inventory/tsauthkey"; do
    [[ -s "$k" ]] && { KEY="$k"; break; }
  done
fi
[[ -n "$KEY" && -s "$KEY" ]] || {
  echo "no Tailscale auth key: save one to ~/.config/inventory/tsauthkey or $SECRETS/tailscale-authkey" >&2
  exit 1
}
[[ -f "$DEPLOY_KEY" ]] || { echo "missing $DEPLOY_KEY (run: bazel run //deploy:garage.keys -- init)" >&2; exit 1; }

SSH_OPTS=(-i "$DEPLOY_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

echo "seeding $KEY -> root@$HOST:/var/lib/tailscale/authkey"
# Over stdin, so the key never appears on a command line.
tr -d '[:space:]' < "$KEY" | ssh "${SSH_OPTS[@]}" "root@$HOST" '
  set -e
  install -d -m700 /var/lib/tailscale
  (umask 077; cat > /var/lib/tailscale/authkey)
  # Logs in from the key if not already logged in; a no-op otherwise.
  systemctl restart tailscaled-autoconnect.service
  # Then put the app on https://<host>.<tailnet>.ts.net.
  systemctl restart inventory-tailscale-serve.service || true
  tailscale status --peers=false | head -1
  tailscale serve status 2>/dev/null | head -3 || true'
echo "done."
