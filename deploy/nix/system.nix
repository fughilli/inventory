# Baked into both the base and full images (sbc-deploy systemModules):
# networking, so a base-only board is still reachable for deploy_live.
{ ... }:
{
  # WiFi comes from deploy/wifi.yaml (sbc_application wifi_config_file).

  # Optional: join your tailnet for remote access + real HTTPS (which enables
  # live QR scanning in the PWA). Then once: `bazel run //deploy:garage.seed_tailscale`
  # and on the Pi: `tailscale serve --bg 80`.
  sbcDeploy.tailscale.enable = true;
}
