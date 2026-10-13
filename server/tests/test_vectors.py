import numpy as np

from inventory.vectors import agglomerate, consolidation_plan, describe_group, distinct_names


def test_agglomerate_separates_clusters():
    rng = np.random.default_rng(0)
    centers = rng.normal(size=(3, 64))
    pts = np.concatenate([c + 0.05 * rng.normal(size=(5, 64)) for c in centers])
    pts /= np.linalg.norm(pts, axis=1, keepdims=True)
    groups = sorted(sorted(g) for g in agglomerate(pts, 0.9))
    assert groups == [list(range(0, 5)), list(range(5, 10)), list(range(10, 15))]
    assert len(agglomerate(pts, 1.1)) == 15


def test_consolidation_targets_majority_bin():
    items = [
        {"id": 1, "bin_code": "B002", "name": "a", "category": "Camping & Outdoor", "tags": ["camping"]},
        {"id": 2, "bin_code": "B002", "name": "b", "category": "Camping & Outdoor", "tags": ["camping"]},
        {"id": 3, "bin_code": "B005", "name": "c", "category": "Camping & Outdoor", "tags": []},
        {"id": 4, "bin_code": None, "name": "d", "category": "", "tags": ["camping"]},
    ]
    plan = consolidation_plan(items)
    assert plan["target_bin"] == "B002" and plan["moves"] == [3, 4]
    assert plan["fragmentation"] == 3
    assert describe_group(items) == "Camping"


def test_repeated_group_names_are_disambiguated():
    a = [{"name": "lantern", "category": "", "tags": ["camping", "light"]},
         {"name": "headlamp", "category": "", "tags": ["camping", "light"]}]
    b = [{"name": "bag", "category": "", "tags": ["camping", "sleep"]},
         {"name": "pad", "category": "", "tags": ["camping", "sleep"]}]
    c = [{"name": "hammer", "category": "Tools", "tags": []},
         {"name": "saw", "category": "Tools", "tags": []}]
    assert distinct_names([a, b, c]) == ["Camping: light", "Camping: sleep", "Tools"]
