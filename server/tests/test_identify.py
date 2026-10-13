"""Identification providers, with the network replaced by fakes."""

import json
from types import SimpleNamespace

from inventory.identify import ClaudeVision, GoogleWebDetection, Identifier, clean_title

WEB = {
    "bestGuessLabels": [{"label": "coleman camp stove"}],
    "webEntities": [{"description": "Camp stove", "score": 0.9}, {"description": "Coleman", "score": 0.8}],
    "pagesWithMatchingImages": [
        {"url": "https://a.example/p", "pageTitle": "Amazon.com : <b>Coleman</b> Classic 2-Burner Propane Stove",
         "fullMatchingImages": [{"url": "x"}]},
        {"url": "https://b.example/q", "pageTitle": "Coleman Classic 2-Burner Propane Stove | eBay"},
    ],
}


def test_google_candidates_from_web_detection():
    cands = GoogleWebDetection.candidates(WEB)
    assert cands[0].name == "Coleman Camp Stove" and cands[0].source == "google"
    assert cands[1].name == "Coleman Classic 2-Burner Propane Stove"
    assert cands[1].confidence > cands[0].confidence  # full image match beats a best guess
    assert len(cands) == 2  # the eBay page dedupes onto the same title
    assert "Camp stove" in cands[0].tags
    assert clean_title("Widget - The Home Depot") == "Widget"


class FakeMessages:
    def __init__(self, content, stop_reason="end_turn"):
        self.content, self.stop_reason, self.calls = content, stop_reason, []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=self.content, stop_reason=self.stop_reason)


def claude_with(content, stop_reason="end_turn"):
    c = object.__new__(ClaudeVision)
    msgs = FakeMessages(content, stop_reason)
    c.client = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
    c.model = "claude-opus-5-5"
    return c, msgs


ANSWER = {"name": "2x4 lumber offcuts", "brand": "", "model": "", "category": "Raw Materials",
          "description": "Short pine 2x4 pieces.", "tags": ["Wood", "lumber"], "confidence": 0.9,
          "alternatives": ["Pine studs"]}


def test_claude_parses_structured_output_and_tolerates_unknown_blocks():
    c, msgs = claude_with([
        {"type": "fallback", "from": {"model": "x"}, "to": {"model": "y"}},  # SDK too old to type it
        SimpleNamespace(type="text", text=json.dumps(ANSWER)),
    ])
    cands = c.identify(b"jpeg", hints=["lumber"])
    assert cands[0].name == "2x4 lumber offcuts" and cands[0].tags == ["wood", "lumber"]
    assert cands[1].name == "Pine studs"
    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["extra_body"]["output_config"]["format"]["type"] == "json_schema"
    assert "lumber" in call["messages"][0]["content"][1]["text"]


def test_claude_refusal_yields_no_candidates():
    c, _ = claude_with([], stop_reason="refusal")
    assert c.identify(b"jpeg") == []


def test_identifier_puts_claude_first_and_isolates_failures():
    ident = Identifier("", "", "m")

    class BrokenGoogle:
        def detect(self, jpeg):
            raise RuntimeError("quota exceeded")

    ident.google = BrokenGoogle()
    ident.claude, _ = claude_with([SimpleNamespace(type="text", text=json.dumps(ANSWER))])
    cands, errors = ident.identify(b"jpeg")
    assert cands[0].source == "claude"
    assert errors == ["google: quota exceeded"]
