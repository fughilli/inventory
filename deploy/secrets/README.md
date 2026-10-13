# Deploy secrets (gitignored)

- `deploy_key` / `deploy_key.pub` — SSH key pair for deploying to the Pi.
  Create with `bazel run //deploy:garage.keys -- init`. The public half is
  baked into the image's root `authorized_keys`.
- `tailscale-authkey` — optional; used by `bazel run //deploy:garage.seed_tailscale`.

API keys for item identification are NOT baked into the image. They live on
the Pi in `/var/lib/inventory/secrets.env` (see the top-level README).
