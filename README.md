# inventory

What's in which bin in the garage. A phone PWA backed by a small server on a
Raspberry Pi, which also drives the 4"×6" thermal label printer.

- **Add items by photo.** Google reverse image search (Cloud Vision web
  detection) and/or Claude name the item. A CLIP image embedding is always
  stored, so custom gear and raw materials are findable by how they look, even
  when nothing names them.
- **Bins.** Each bin gets a code (`B001`…) and a printed label with a big code
  and a QR code. The QR opens that bin in the app, even from the phone's stock
  camera.
- **Packing.** "Pack this bin" puts you in a mode where each photo you take goes
  straight into that bin.
- **Search.** Keyword search plus semantic visual search ("something orange",
  "camping") over item photos. You can also search with a photo.
- **Check out / check in.** Mark what you take out. The *Check in* tab is the
  manifest of everything that's out, grouped by the bin it goes back to.
- **Tidy up.** Clusters related items (by photo + name/tags) and suggests which
  bin to consolidate each scattered group into.

```
phone (PWA) ──http──▶ inventory server (FastAPI, SQLite, CLIP/ONNX)  :80
                          │  ├─ Google Cloud Vision (web detection)   optional
                          │  └─ Claude (vision)                         optional
                          └─http──▶ printd ──TSPL──▶ /dev/usb/lp0 ──▶ KNAON Y813BT
                                    127.0.0.1:8631
```

| Dir | What |
| --- | --- |
| `server/` | FastAPI app: API, SQLite schema, identification, embeddings, grouping, label rendering |
| `web/` | The PWA (vanilla TypeScript + Vite) |
| `printd/` | Print agent: image → TSPL → USB printer |
| `deploy/` | Raspberry Pi image + live deploy via [sbc-deploy](https://github.com/fughilli/sbc-deploy) |

## The printer

The KNAON Y813BT (Amazon B0DR86V4ZV) is a 203 dpi 4"×6" label printer. Over
USB it speaks **TSPL**: KNAON's own Linux driver is the CUPS `rastertolabel`
filter emitting `SIZE / GAP / DENSITY / CLS / BITMAP / PRINT`. So `printd`
writes TSPL straight to the kernel's `usblp` device. It needs no CUPS and no
vendor binary. Its Bluetooth mode only works with the vendor's phone app, so
use the USB cable.

First time with a new roll, on the Pi:

```sh
curl -X POST localhost:8631/calibrate   # measure the label gap
curl -X POST localhost:8631/test        # print a test pattern
```

Fixes, in `/var/lib/inventory/printd.env` (then `systemctl restart sbc-printd`):

| Symptom | Setting |
| --- | --- |
| Upside down | `PRINTD_DIRECTION=1` |
| Too light / dark | `PRINTD_DENSITY=0..15` (default 8) |
| Prints a negative, or blank black | `PRINTD_INVERT=1` |
| Labels drift across the gap | `PRINTD_GAP_MM=…` (default 3), then recalibrate |

## Deploying the Pi

You need `nix` (flakes enabled) and `bazelisk` on your workstation. Pi 4 or 5
recommended; the board is set in `deploy/BUILD.bazel`.

```sh
cp deploy/wifi.yaml.example deploy/wifi.yaml            # your WiFi (gitignored)
bazel run //deploy:garage.keys -- init                  # deploy SSH key, once
bazel run //deploy:garage.image_sd -- --device /dev/sdX # build + flash the card
```

Boot the Pi, plug in the printer, and open **http://garage.local** on your
phone. Add it to the home screen: Share → *Add to Home Screen* on iOS, or the
install prompt on Android.

Updates after the first flash:

```sh
bazel run //deploy:garage.deploy_live -- garage.local
```

### API keys (optional, recommended)

Keys never go in the image. Put them on the Pi:

```sh
bazel run //deploy:garage.ssh
cat > /var/lib/inventory/secrets.env <<'EOF'
GOOGLE_VISION_API_KEY=...        # Cloud Vision API key (web detection)
ANTHROPIC_API_KEY=...            # Claude identification + group naming
# INVENTORY_CLAUDE_MODEL=claude-opus-5-5   # the default
EOF
chmod 600 /var/lib/inventory/secrets.env && systemctl restart sbc-inventory
```

With neither key, you still get CLIP visual search, lookalike matching, and
grouping. You just type item names yourself.

- **Google**: enable *Cloud Vision API* on a GCP project and create an API key.
  Web detection is Google's reverse image search, the best match for
  store-bought products.
- **Claude** sees the photo plus Google's hints. It handles custom equipment
  and raw materials, and it categorises and tags every item.

### HTTPS / remote access (Tailscale)

The PWA works over plain `http://garage.local`. Photos use the native camera,
and bin QR codes are read from a snapshot. Live viewfinder QR scanning needs
HTTPS, which Tailscale provides. The image includes `tailscaled`, which logs in
from an auth key at `/var/lib/tailscale/authkey` on the Pi. The key is never
baked into the image. Make a key at
<https://login.tailscale.com/admin/settings/keys>, save it as
`~/.config/inventory/tsauthkey` (shared with the Docker setup) or
`deploy/secrets/tailscale-authkey`, and after flashing a card run:

```sh
bazel run //deploy:seed_tailscale_authkey    # [-- host], default garage.local
```

This copies the key over, joins the tailnet as `garage`, and serves the app at
`https://garage.<tailnet>.ts.net`. HTTPS needs MagicDNS and HTTPS certificates
turned on for the tailnet (admin console → DNS). The node stays joined across
reboots and redeploys; only a reflash wipes `/var/lib`, so re-run it then.

Then set `INVENTORY_PUBLIC_URL=https://garage.<tailnet>.ts.net` in
`secrets.env` before printing labels, so their QR codes point at the HTTPS
address. Labels printed earlier keep their old URL (and `http://garage.local/b/…` keeps
working at home).

## Running in Docker (on your tailnet)

To run the server on any Docker host instead of (or before) the Pi, with a
Tailscale sidecar that puts it on your tailnet:

```sh
mkdir -p ~/.config/inventory
(umask 077; cat > ~/.config/inventory/tsauthkey)   # paste the auth key, Ctrl-D
docker/inventory.sh up                             # builds, starts, prints the URL
```

It joins the tailnet as `inventory` (`TS_HOSTNAME=…` to change it) and serves
`https://inventory.<tailnet>.ts.net`. It's also at `http://127.0.0.1:8080`
on the host. The auth key is only needed for the first start, because the node's
state is kept.

| What | Where |
| --- | --- |
| Database, photos, CLIP model, Tailscale state | `~/.local/share/inventory/` (`INVENTORY_HOME`) |
| API keys (`GOOGLE_VISION_API_KEY=…`, `ANTHROPIC_API_KEY=…`) | `~/.config/inventory/secrets.env` |
| Printer overrides (`PRINTD_*`) | `~/.config/inventory/printd.env` |

Other commands: `docker/inventory.sh down | restart | logs [service] | status | url`.
With the label printer plugged into the Docker host (Linux only), use
`docker/inventory.sh up --printer`, or pass `--printer /dev/usb/lp1` to pick
the device; that also runs `printd` in the stack.

Label QR codes point at whatever address you opened the app from, normally the
`ts.net` one. Set `INVENTORY_PUBLIC_URL` to pin them.

### Backups

Everything lives in `/var/lib/inventory` on the Pi: `inventory.db` (SQLite),
`photos/`, and the downloaded CLIP model in `models/`, which can be re-fetched.

## Development

```sh
# server (Python 3.11+, uv)
cd server && uv sync --all-extras
uv run pytest
INVENTORY_DATA_DIR=./data uv run inventory-server     # :8080, serves web/dist if built

# web
cd web && npm install
npm run dev          # Vite on :5173, proxies /api and /photos to :8080
npm run build        # -> web/dist, served by the server

# printd
cd printd && uv sync && uv run pytest
PRINTD_DEVICE=/dev/usb/lp0 uv run printd             # or a plain file to capture jobs
uv run printd encode label.png out.tspl              # inspect a job offline
```

The CLIP model (~150 MB, quantised ViT-B/32) downloads into the data dir on
first start. `INVENTORY_EMBED=0` turns it off. To run the real-model test:
`INVENTORY_TEST_MODEL_DIR=<dir with vision.onnx, text.onnx, tokenizer.json> uv run pytest`.

### How the Pi build works

`bazel run //deploy:garage.*` stages `deploy/nix/*.nix` plus the app sources
(re-rooted as `src/{server,web,printd}` by `deploy/nix/defs.bzl`) into a
hermetic tree. Nix builds the three packages from that tree in
`deploy/nix/packages.nix`. The server and printd run their unit tests during the
build, and the web build uses `importNpmLock`, so there's no npm hash to
maintain. The sbc-deploy version is pinned twice and must match: the
`git_override` in `MODULE.bazel`, and the flake input in `deploy/nix/flake.nix`
(+ `flake.lock`).

## Later: the bench

The planned overhead-camera bench (scan the bin QR, show contents on a tablet,
track items going in and out) builds on what's here. The bench can be another
client of the same HTTP API (`/api/bins/{code}`, `/api/items/move`,
`/api/items/checkout`, `/api/search/image`), and the CLIP index already does
"which item is this?" by photo.
