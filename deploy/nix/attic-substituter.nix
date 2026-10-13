# Trusted substituter on the Pi: the self-hosted Attic nix cache (tailnet node
# `attic`, shared with the splanc project). Lets a deploy's
# `nix copy --substitute-on-destination` pull closure paths straight from the
# cache over the tailnet instead of through the deployer's uplink. Pull is
# anonymous; the tag:attic tailnet ACL is the access boundary. The build-time
# counterpart is `nixConfig` in flake.nix; keep the two in sync.
{ lib, ... }:
{
  nix.settings = {
    extra-substituters = [ "http://attic.tail6b8ad3.ts.net:8080/splanc" ];
    extra-trusted-public-keys = [ "splanc:MWmTqIgwyOOGTh2wazhPPnVAsIIAV9pEXqhhorIWdvw=" ];
    # An unreachable cache must not stall a build (e.g. before the Pi joins the tailnet).
    connect-timeout = lib.mkDefault 5;
    fallback = lib.mkDefault true;
  };
}
