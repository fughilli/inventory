{
  # The garage Pi: inventory server + PWA + label-printer agent.
  #
  # Built through Bazel (`bazel run //deploy:garage.<mode>`), which stages this
  # directory plus the app sources (as ./src) into a hermetic tree first — so
  # `./src` only exists in that staged copy, not in the git checkout.
  description = "garage inventory Pi";

  # Build-time substituter for the machine that BUILDS the closure (this
  # workstation): pulls the kernel etc. from the self-hosted Attic cache instead
  # of rebuilding. sbc-deploy passes --accept-flake-config, so this is honored
  # non-interactively. The on-Pi counterpart is nix/attic-substituter.nix.
  # Same cache as the splanc project (tools/attic-cache there).
  nixConfig = {
    extra-substituters = [ "http://attic.tail6b8ad3.ts.net:8080/splanc" ];
    extra-trusted-public-keys = [ "splanc:MWmTqIgwyOOGTh2wazhPPnVAsIIAV9pEXqhhorIWdvw=" ];
  };

  inputs = {
    # Keep in sync with the git_override commit in /MODULE.bazel.
    sbc-deploy.url = "github:fughilli/sbc-deploy/e1dfe97b07a8a0cd2339604d14e262e0903eca26?dir=nix";
  };

  outputs = { self, sbc-deploy, ... }:
    sbc-deploy.lib.mkSbcProject {
      hostName = "garage";
      # Board comes from the Bazel `board` attr ($SBC_BOARD).
      appModules = [ ./inventory.nix ./attic-substituter.nix ];
      systemModules = [ ./system.nix ];
    };
}
