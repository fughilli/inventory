import pytest

from inventory.store import Invalid, NotFound, normalize_bin_code


def test_bin_codes_are_sequential_and_normalised(store):
    assert store.create_bin()["code"] == "B001"
    assert store.create_bin("b7")["code"] == "B007"
    assert store.create_bin()["code"] == "B008"
    assert normalize_bin_code(" 1234 ") == "B1234"
    with pytest.raises(Invalid):
        store.create_bin("B7")
    with pytest.raises(Invalid):
        normalize_bin_code("shelf")


def test_item_lifecycle_and_manifest(store):
    store.create_bin(name="Camping")
    store.create_bin(name="Tools")
    tent = store.create_item("Coleman Sundome tent", bin_code="B001", category="Camping & Outdoor",
                             tags="camping, Tent ,camping")
    assert tent["tags"] == ["camping", "tent"]
    assert tent["bin_code"] == "B001" and not tent["checked_out"]
    drill = store.create_item("DeWalt drill", bin_code="B002")
    pegboard = store.create_item("Shop vac", location_note="under the bench")

    store.check_out([tent["id"], drill["id"], pegboard["id"]], note="trip")
    m = store.checkin_manifest()
    assert m["count"] == 3
    assert [g["bin_code"] for g in m["groups"]] == ["B001", "B002", None]
    # Home bin survives check-out.
    assert store.get_item(tent["id"])["bin_code"] == "B001"

    store.check_in([tent["id"]])
    store.check_in([drill["id"]], bin_code="B001")  # returned to a different bin
    d = store.get_item(drill["id"], with_detail=True)
    assert d["bin_code"] == "B001" and not d["checked_out"]
    assert [e["kind"] for e in d["events"]][:2] == ["moved", "checked_out"]
    assert store.checkin_manifest()["count"] == 1
    assert store.get_bin("B001")["item_count"] == 2


def test_fts_prefix_and_bin_search(store):
    store.create_bin(name="Christmas lights")
    store.create_item("Phillips screwdriver set", bin_code="B001", tags=["hand tools"])
    store.create_item("LED string", bin_code="B001")
    store.create_item("Garden hose")
    assert len(store.fts_search("screwd")) == 1
    assert len(store.fts_search("christmas")) == 2  # via the bin name
    assert store.fts_search("B001") != []
    assert store.fts_search('"; DROP') == []


def test_update_and_delete(store):
    store.create_bin()
    it = store.create_item("thing", bin_code="B001")
    it = store.update_item(it["id"], name="Better thing", tags=["a", "b"], quantity=0)
    assert it["name"] == "Better thing" and it["quantity"] == 1
    assert store.fts_search("better") == [it["id"]]
    with pytest.raises(Invalid):
        store.delete_bin("B001")
    store.move_items([it["id"]], None)
    store.delete_bin("B001")
    store.delete_item(it["id"])
    with pytest.raises(NotFound):
        store.get_item(it["id"])
