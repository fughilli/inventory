# Deploy secrets (gitignored)

- `deploy_key` / `deploy_key.pub` — SSH key pair for deploying to the Pi.
  Create with `bazel run //deploy:garage.keys -- init`. The public half is
  baked into the image's root `authorized_keys`.
- `tailscale-authkey` — optional; the Tailscale auth key that
  `bazel run //deploy:seed_tailscale_authkey` copies to the Pi's
  `/var/lib/tailscale/authkey`. If it's absent, the script uses
  `~/.config/inventory/tsauthkey` (the key the Docker setup reads).

API keys for item identification are NOT baked into the image. They live on
the Pi in `/var/lib/inventory/secrets.env` (see the top-level README).
