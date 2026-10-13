{
  # The garage Pi: inventory server + PWA + label-printer agent.
  #
  # Built through Bazel (`bazel run //deploy:garage.<mode>`), which stages this
  # directory plus the app sources (as ./src) into a hermetic tree first — so
  # `./src` only exists in that staged copy, not in the git checkout.
  description = "garage inventory Pi";

  inputs = {
    # Keep in sync with the git_override commit in /MODULE.bazel.
    sbc-deploy.url = "github:fughilli/sbc-deploy/e1dfe97b07a8a0cd2339604d14e262e0903eca26?dir=nix";
  };

  outputs = { self, sbc-deploy, ... }:
    sbc-deploy.lib.mkSbcProject {
      hostName = "garage";
      # Board comes from the Bazel `board` attr ($SBC_BOARD).
      appModules = [ ./inventory.nix ];
      systemModules = [ ./system.nix ];
    };
}
