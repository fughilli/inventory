# The application half of the image: the inventory server (port 80) and the
# label-printer agent (localhost:8631), as sbc-deploy hardened services.
{ config, lib, pkgs, ... }:
let
  pkgsInv = pkgs.callPackage ./packages.nix { };
  host = config.networking.hostName;
in
{
  services.sbcApps.inventory = {
    description = "Garage inventory (web app + API)";
    package = pkgsInv.server;
    exec = "bin/inventory-server";
    ports = [ 80 ];
    bindPrivilegedPorts = true;
    stateDirectory = "inventory"; # /var/lib/inventory: db, photos, CLIP model
    environment = {
      INVENTORY_DATA_DIR = "/var/lib/inventory";
      INVENTORY_WEB_DIR = "${pkgsInv.web}";
      INVENTORY_PORT = "80";
      INVENTORY_PRINTD_URL = "http://127.0.0.1:8631";
      # What bin-label QR codes point at. Override in secrets.env, e.g. with
      # your Tailscale HTTPS name (https://garage.<tailnet>.ts.net).
      INVENTORY_PUBLIC_URL = "http://${host}.local";
    };
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    extraServiceConfig = {
      # API keys (GOOGLE_VISION_API_KEY, ANTHROPIC_API_KEY) and overrides live
      # on the board only, never in the Nix store. Optional ("-").
      EnvironmentFile = "-/var/lib/inventory/secrets.env";
      MemoryHigh = "900M";
    };
  };

  services.sbcApps.printd = {
    description = "Label printer agent (TSPL over USB)";
    package = pkgsInv.printd;
    exec = "bin/printd";
    extraGroups = [ "lp" ];
    environment = {
      PRINTD_HOST = "127.0.0.1";
      PRINTD_PORT = "8631";
      PRINTD_LABEL = "4x6";
      PRINTD_DENSITY = "8";
      # Flip to 1 if labels come out upside down.
      PRINTD_DIRECTION = "0";
    };
    extraServiceConfig.EnvironmentFile = "-/var/lib/inventory/printd.env";
  };

  # https://<host>.<tailnet>.ts.net -> the app, once the board is on the
  # tailnet (see system.nix). Serve config persists in tailscaled's state, so
  # this only (re)asserts it. Not logged in yet: exits quietly, and the
  # seed_tailscale_authkey script restarts it after seeding. Needs HTTPS
  # certificates enabled for the tailnet (admin console -> DNS).
  systemd.services.inventory-tailscale-serve = lib.mkIf config.services.tailscale.enable {
    description = "Serve the inventory app over HTTPS on the tailnet";
    after = [ "tailscaled.service" "tailscaled-autoconnect.service" ];
    wants = [ "tailscaled.service" ];
    wantedBy = [ "multi-user.target" ];
    path = [ config.services.tailscale.package ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      for _ in $(seq 30); do
        tailscale status --peers=false >/dev/null 2>&1 && break
        sleep 2
      done
      if ! tailscale status --peers=false >/dev/null 2>&1; then
        echo "not logged in to the tailnet; skipping serve"
        exit 0
      fi
      tailscale serve --bg http://127.0.0.1:80
    '';
  };

  # USB printer class device -> /dev/usb/lp0, writable by the lp group.
  boot.kernelModules = [ "usblp" ];
  services.udev.extraRules = ''
    SUBSYSTEM=="usbmisc", KERNEL=="lp[0-9]*", GROUP="lp", MODE="0660"
  '';
}
