# Baked into both the base and full images (sbc-deploy systemModules):
# networking, so a base-only board is still reachable for deploy_live.
{ ... }:
{
  # WiFi comes from deploy/wifi.yaml (sbc_application wifi_config_file).

  # Tailscale: remote access + real HTTPS (which enables live QR scanning in the
  # PWA). The auth key is seeded out of band, never in git or the Nix store:
  #   bazel run //deploy:seed_tailscale_authkey
  # tailscaled-autoconnect logs in from it on a fresh state dir (e.g. after a
  # reflash) and is a no-op once logged in. The tailnet name is the hostname.
  sbcDeploy.tailscale = {
    enable = true;
    authKeyFile = "/var/lib/tailscale/authkey";
  };
}
