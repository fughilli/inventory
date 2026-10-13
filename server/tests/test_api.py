from fastapi.testclient import TestClient

from inventory.app import create_app

from .conftest import jpeg


class FakePrinter:
    def __init__(self):
        self.jobs = []

    def print_image(self, img, copies=1):
        self.jobs.append((img.size, copies))
        return {"ok": True}

    def status(self):
        return {"reachable": True, "device": "/dev/usb/lp0", "present": True}


def client(cfg):
    app = create_app(cfg)
    return app, TestClient(app)


def test_end_to_end_flow(cfg):
    app, c = client(cfg)
    with c:
        assert c.get("/api/status").json()["identify"] == {"google": False, "claude": False}

        r = c.post("/api/bins", json={"name": "Camping", "location": "Rack A"}).json()
        code = r["bins"][0]["code"]
        assert code == "B001"
        assert c.post("/api/bins", json={"count": 3}).json()["bins"][-1]["code"] == "B004"

        # Identify with no providers still stores the photo and returns cleanly.
        ident = c.post("/api/identify", files={"file": ("x.jpg", jpeg(), "image/jpeg")}).json()
        assert ident["candidates"] == [] and ident["photo_id"]

        item = c.post("/api/items", json={"name": "Tent stakes", "bin_code": code,
                                         "photo_ids": [ident["photo_id"]], "tags": ["camping"]}).json()
        assert item["primary_photo_id"] == ident["photo_id"]
        assert c.get(f"/photos/{ident['photo_id']}/thumb.jpg").status_code == 200

        assert c.get("/api/search", params={"q": "stake"}).json()["items"][0]["id"] == item["id"]
        b = c.get(f"/api/bins/{code.lower()}").json()
        assert b["items"][0]["name"] == "Tent stakes"

        c.post("/api/items/checkout", json={"item_ids": [item["id"]]})
        m = c.get("/api/manifest").json()
        assert m["count"] == 1 and m["groups"][0]["bin_code"] == "B001"
        c.post("/api/items/checkin", json={"item_ids": [item["id"]]})
        assert c.get("/api/manifest").json()["count"] == 0

        png = c.get(f"/api/bins/{code}/label.png")
        assert png.headers["content-type"] == "image/png"

        fake = FakePrinter()
        app.state.printer.print_image = fake.print_image
        r = c.post("/api/print", json={"codes": ["B001", "B002"], "copies": 2})
        assert r.status_code == 200, r.text
        assert fake.jobs == [((812, 1218), 2), ((812, 1218), 2)]
        assert c.post("/api/print", json={"codes": ["B999"]}).status_code == 404
        assert fake.jobs[-1] == ((812, 1218), 2)  # nothing printed for the bad batch

        g = c.get("/api/groups").json()
        assert g["method"] == "category"

        assert c.get("/api/items/999").status_code == 404
        assert c.post("/api/items", json={"name": " "}).status_code == 400
        assert c.post("/api/identify", files={"file": ("x.jpg", b"nope", "image/jpeg")}).status_code == 400
