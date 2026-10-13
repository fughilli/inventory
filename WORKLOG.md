# WORKLOG

Read this first when resuming. Newest entries on top; keep "Open threads"
current.

## Open threads

- **Not yet run on real hardware.** No Pi has been flashed and no label printed
  on the actual KNAON Y813BT. Things to confirm on first contact:
  1. TSPL bitmap polarity (`printd/printd/tspl.py`: PIL "1" bits, 1 = blank).
     If labels print as negatives, set `PRINTD_INVERT=1` and flip the default
     in code.
  2. Orientation (`PRINTD_DIRECTION`) and the gap (`GAPDETECT` via
     `POST /calibrate`).
  3. That the printer enumerates as a USB printer-class device
     (`/dev/usb/lp0`). If it only shows up as a vendor HID/CDC device, printd
     needs a different transport.
- **Google / Claude identification is untested against the live APIs** (no keys
  in the dev container). Both are covered by offline tests with recorded/fake
  responses (`server/tests/test_identify.py`).
- **Full NixOS image not built here.** The three packages build and pass their
  tests under the pinned nixpkgs (aarch64-linux, via nix-portable). The
  board's full system closure / SD image was not built.
- The bench (overhead camera + tablet) is future work; see README "Later".
- **Docker stack never run** (no docker in the dev container). See the
  Docker + Tailscale entry below for what was checked instead.

## 2026-10-13 — Docker + Tailscale

Run the server on any Docker host, on the tailnet (`docker/`, driven by
`docker/inventory.sh up|down|logs|status|url|shell`):
- **tailscale sidecar** (`tailscale/tailscale`) in userspace mode
  (`TS_USERSPACE=true`: no tun/NET_ADMIN, works on Docker Desktop). Auth key via
  `TS_AUTHKEY=file:/run/secrets/tsauthkey`, mounted from
  `~/.config/inventory/tsauthkey`. `TS_AUTH_ONCE` plus persisted state, so the key
  is only needed for the first join. `TS_SERVE_CONFIG=serve.json` uses
  `${TS_CERT_DOMAIN}` to serve `https://<TS_HOSTNAME>.<tailnet>.ts.net` ->
  `127.0.0.1:8080`.
- **server** shares the sidecar's network namespace
  (`network_mode: service:tailscale`) and runs as the invoking uid/gid. Data
  lives in `$INVENTORY_HOME` (default `~/.local/share/inventory`).
- **printd** sits behind the optional compose profile `printer`
  (`up --printer [/dev/usb/lpN]`), in the same image.

Pi: `sbcDeploy.tailscale.authKeyFile = /var/lib/tailscale/authkey` (system.nix),
seeded out of band by `bazel run //deploy:seed_tailscale_authkey [-- host]`
(splanc pi/hitl pattern: key over ssh stdin, then restart
tailscaled-autoconnect). A new `inventory-tailscale-serve` oneshot
(inventory.nix) runs `tailscale serve --bg http://127.0.0.1:80` once logged in.

Verification: static review only so far. The agent shell was broken (EIO), so
none of the planned checks ran: bash -n/shellcheck, compose/serve.json parse,
fake-docker simulation of inventory.sh, the pip install of the Dockerfile
packages, the bazel build of `//deploy:seed_tailscale_authkey`, and the Nix
eval. Fix found in review: `ts_name` failed under `set -eo pipefail` while
tailscale wasn't up yet (`|| true` added).

## 2026-10-13 — initial build

Built from an empty repo: server (FastAPI + SQLite + CLIP-ONNX), web PWA
(vanilla TS + Vite), printd (TSPL print agent), Pi deployment (sbc-deploy).

Decisions and why:
- **Printer protocol = TSPL over usblp**, found by unpacking KNAON's Raspberry
  Pi driver (`Knaon-RasPi-Driver-Latest_Ver1.1.1.run` → CUPS `rastertolabel`,
  whose strings show `SIZE/GAP/DENSITY/CLS/BITMAP/PRINT`). Avoids running an
  aarch64 vendor binary on NixOS.
- **Server renders the label PNG; printd only prints pixels**, so the
  in-app preview is exactly what prints, and printd stays generic.
- **One Pi runs everything** (server on :80, printd on 127.0.0.1:8631).
  printd is a separate service so a future bench or another host can share it.
- **Item `bin_id` is the HOME bin and survives check-out**; `checked_out_at`
  is the out flag. That's what makes the check-in manifest possible.
- **CLIP scores are relative, not absolute.** The quantised ViT-B/32 scores
  unrelated objects at 0.75–0.8 image-to-image and ~0.25 text-to-image, so
  semantic search keeps items whose score stands out from the collection
  (z ≥ 1.6), and "you may already have this" requires ≥ 0.86. Clustering
  centres each modality on the collection mean and weights text 2×. Default
  threshold 0.3 was tuned on 20 real photos.
- **Deploy staging:** sbc-deploy only stages files under the flake dir, so
  `deploy/nix/defs.bzl` (`flake_srcs`) re-roots the app sources to
  `deploy/nix/src/…`. Nix then builds from plain paths (no IFD); the web build
  uses `importNpmLock` (no npm hash).
- sbc-deploy is pinned at e1dfe97 in BOTH `MODULE.bazel` and
  `deploy/nix/flake.nix`/`flake.lock`. Bump them together.

Verification done:
- `server`: 12 tests (+1 real-CLIP test, opt-in via `INVENTORY_TEST_MODEL_DIR`).
- `printd`: 4 tests, including HTTP → fake device file.
- Nix: `server`, `printd`, `web` built with the flake-locked nixpkgs on
  aarch64-linux, with their test suites passing in the build.
- PWA driven end to end with Playwright at phone size (add, pack, check
  out/in, manifest, groups, print), light and dark.

Dev-container gotchas (not repo problems):
- Playwright's Chromium needed libs extracted from Ubuntu debs (no sudo);
  keystrokes into `type=search` inputs don't register in that build. Use
  `dispatchEvent` in scripts.
- nix-portable only has proot here: stdenv `cp -p` unpack and the Python
  wrapper fail on permission calls, so verification used an overridden unpack
  and `dontWrapPythonPrograms`.
