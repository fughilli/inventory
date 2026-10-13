"""printd HTTP server.

    GET  /status             device presence + config
    POST /print?copies=N     body: PNG/JPEG -> fitted onto the label and printed
    POST /test               print a calibration/test pattern
    POST /calibrate          GAPDETECT (run after loading a new roll)

Configured by env: PRINTD_DEVICE (default: first /dev/usb/lp*), PRINTD_PORT
(8631), PRINTD_HOST, PRINTD_DENSITY, PRINTD_SPEED, PRINTD_DIRECTION,
PRINTD_INVERT, PRINTD_GAP_MM, PRINTD_LABEL ("4x6").

CLI helpers for bench testing without HTTP:
    printd encode in.png out.tspl     # write the raw job to a file
    printd print in.png               # print directly to the device
"""

from __future__ import annotations

import glob
import io
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image

from . import tspl

log = logging.getLogger("printd")
MAX_BODY = 20 * 1024 * 1024


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name, "")
    return int(v) if v.strip() else default


def config_from_env() -> tuple[tspl.Media, tspl.Settings]:
    w, h = (float(x) for x in os.environ.get("PRINTD_LABEL", "4x6").lower().split("x"))
    media = tspl.Media(width_in=w, height_in=h, gap_mm=float(os.environ.get("PRINTD_GAP_MM", "3")))
    settings = tspl.Settings(
        density=_env_int("PRINTD_DENSITY", 8),
        speed=_env_int("PRINTD_SPEED", 4),
        direction=_env_int("PRINTD_DIRECTION", 0),
        invert=os.environ.get("PRINTD_INVERT", "0").lower() in ("1", "true", "yes"),
    )
    return media, settings


class Printer:
    def __init__(self, device: str | None, media: tspl.Media, settings: tspl.Settings):
        self.device_override = device
        self.media, self.settings = media, settings
        self.lock = threading.Lock()
        self.jobs = 0
        self.last_error: str | None = None

    @property
    def device(self) -> str | None:
        if self.device_override:
            return self.device_override
        found = sorted(glob.glob("/dev/usb/lp*"))
        return found[0] if found else None

    def status(self) -> dict:
        dev = self.device
        return {
            "device": dev,
            "present": bool(dev and os.path.exists(dev)),
            "writable": bool(dev and os.access(dev, os.W_OK)),
            "label": f"{self.media.width_in:g}x{self.media.height_in:g}in",
            "dots": [self.media.width_dots, self.media.height_dots],
            "dpi": tspl.DPI,
            "density": self.settings.density,
            "jobs": self.jobs,
            "last_error": self.last_error,
        }

    def send(self, job: bytes) -> None:
        dev = self.device
        if not dev or not os.path.exists(dev):
            raise RuntimeError("printer not connected (no /dev/usb/lp*)")
        with self.lock:
            try:
                # usblp blocks until the printer has accepted the data.
                with open(dev, "wb", buffering=0) as f:
                    view = memoryview(job)
                    while view:
                        n = f.write(view[:65536])
                        view = view[n:]
                self.jobs += 1
                self.last_error = None
            except OSError as e:
                self.last_error = str(e)
                raise

    def print_image(self, img: Image.Image, copies: int = 1) -> dict:
        t = time.monotonic()
        job = tspl.encode(img, self.media, self.settings, copies)
        self.send(job)
        return {"ok": True, "bytes": len(job), "copies": copies, "ms": round((time.monotonic() - t) * 1000)}


def make_handler(printer: Printer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "printd/0.1"

        def log_message(self, fmt, *args):  # route through logging
            log.info("%s %s", self.address_string(), fmt % args)

        def _json(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urlparse(self.path).path == "/status":
                return self._json(200, printer.status())
            self._json(404, {"detail": "not found"})

        def do_POST(self):
            url = urlparse(self.path)
            qs = parse_qs(url.query)
            try:
                if url.path == "/print":
                    n = int(self.headers.get("Content-Length", "0"))
                    if not 0 < n <= MAX_BODY:
                        return self._json(400, {"detail": "body must be an image (<= 20 MB)"})
                    copies = int(qs.get("copies", ["1"])[0])
                    if not 1 <= copies <= 50:
                        return self._json(400, {"detail": "copies must be 1..50"})
                    try:
                        img = Image.open(io.BytesIO(self.rfile.read(n)))
                        img.load()
                    except Exception as e:  # noqa: BLE001
                        return self._json(400, {"detail": f"not an image: {e}"})
                    return self._json(200, printer.print_image(img, copies))
                if url.path == "/test":
                    return self._json(200, printer.print_image(tspl.test_pattern(printer.media)))
                if url.path == "/calibrate":
                    printer.send(tspl.calibrate())
                    return self._json(200, {"ok": True})
                self._json(404, {"detail": "not found"})
            except (OSError, RuntimeError) as e:
                log.warning("print failed: %s", e)
                self._json(503, {"detail": str(e)})

    return Handler


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    media, settings = config_from_env()
    printer = Printer(os.environ.get("PRINTD_DEVICE") or None, media, settings)
    if argv[:1] == ["encode"] and len(argv) == 3:
        with open(argv[2], "wb") as f:
            f.write(tspl.encode(Image.open(argv[1]), media, settings))
        return
    if argv[:1] == ["print"] and len(argv) == 2:
        print(json.dumps(printer.print_image(Image.open(argv[1]))))
        return
    if argv:
        sys.exit(__doc__)
    host = os.environ.get("PRINTD_HOST", "127.0.0.1")
    port = _env_int("PRINTD_PORT", 8631)
    srv = ThreadingHTTPServer((host, port), make_handler(printer))
    log.info("printd on %s:%d, device=%s", host, port, printer.device)
    srv.serve_forever()


if __name__ == "__main__":
    main()
