import io
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from PIL import Image, ImageDraw

from printd import tspl
from printd.__main__ import Printer, make_handler


def split_job(job: bytes):
    """-> (header text, bytes/row, rows, bitmap bytes, trailer text)"""
    i = job.index(b"BITMAP ")
    _x, _y, wb, h, _mode, rest = job[i + 7:].split(b",", 5)
    n = int(wb) * int(h)
    return job[:i].decode(), int(wb), int(h), rest[:n], rest[n:].decode()


def test_job_shape_and_polarity():
    img = Image.new("L", (812, 1218), 255)
    ImageDraw.Draw(img).rectangle([0, 0, 7, 0], fill=0)  # first 8 px of row 0 black
    head, wb, h, data, tail = split_job(tspl.encode(img, copies=3))
    assert "SIZE 4,6" in head and "GAP 3 mm,0 mm" in head and "DENSITY 8" in head
    assert head.rstrip().endswith("CLS")
    assert (wb, h) == (102, 1218)
    assert len(data) == 102 * 1218
    assert data[0] == 0x00          # black -> 0 bits (burn)
    assert data[1] == 0xFF          # white -> 1 bits
    assert data[wb] == 0xFF         # row 1 untouched
    assert tail.strip() == "PRINT 1,3"


def test_landscape_is_rotated_and_fitted():
    bw = tspl.fit(Image.new("RGB", (1800, 1200), "white"), tspl.Media())
    assert bw.size == (812, 1218) and bw.mode == "1"


def test_invert_flag():
    img = Image.new("L", (812, 1218), 255)
    _, _, _, data, _ = split_job(tspl.encode(img, settings=tspl.Settings(invert=True)))
    assert data[0] == 0x00


def test_http_print_to_fake_device(tmp_path):
    dev = tmp_path / "lp0"
    dev.write_bytes(b"")
    p = Printer(str(dev), tspl.Media(), tspl.Settings())
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        st = json.load(urllib.request.urlopen(base + "/status"))
        assert st["present"] and st["dots"] == [812, 1218]
        buf = io.BytesIO()
        Image.new("RGB", (400, 600), "white").save(buf, "PNG")
        req = urllib.request.Request(base + "/print?copies=2", data=buf.getvalue(),
                                     headers={"Content-Type": "image/png"})
        r = json.load(urllib.request.urlopen(req))
        assert r["ok"] and r["copies"] == 2
        assert dev.read_bytes().endswith(b"PRINT 1,2\r\n")
    finally:
        srv.shutdown()
