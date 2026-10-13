"""Item identification from a photo.

Two pluggable providers, each optional (enabled by its API key):

  * GoogleWebDetection — Cloud Vision WEB_DETECTION, i.e. Google's reverse image
    search: best-guess label, web entities, and product pages showing the same
    image. Great for retail products; useless for custom stuff.
  * ClaudeVision — asks Claude to name/describe/categorise what's in the photo,
    seeded with Google's hints when available. Handles raw materials, custom
    equipment, and generic objects that reverse search can't.

The CLIP "similar items you already own" matches are added by the API layer, so
there is always *something* useful even with no keys configured.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import asdict, dataclass, field

import httpx

log = logging.getLogger(__name__)

CATEGORIES = [
    "Tools", "Power Tools", "Hardware & Fasteners", "Electrical", "Electronics",
    "Camping & Outdoor", "Sports & Fitness", "Bikes", "Holiday & Seasonal",
    "Automotive", "Garden & Yard", "Household", "Kitchen", "Crafts & Hobby",
    "Raw Materials", "Paint & Chemicals", "Plumbing", "Safety Gear",
    "Documents & Keepsakes", "Toys & Games", "Clothing", "Cables & Adapters",
    "Other",
]


@dataclass
class Candidate:
    name: str
    source: str
    description: str = ""
    category: str = ""
    brand: str = ""
    model: str = ""
    tags: list[str] = field(default_factory=list)
    url: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


_TITLE_JUNK = re.compile(
    r"^(amazon\.com\s*:\s*|amazon\.com\.\w+\s*:\s*|ebay\s*[:|-]\s*)|"
    r"(\s*[|:-]\s*(amazon\.com|ebay|walmart\.com|the home depot|lowe's|target|etsy).*$)",
    re.I,
)


def clean_title(t: str) -> str:
    t = re.sub(r"<[^>]+>", "", t)  # pageTitle comes with <b> highlight tags
    t = _TITLE_JUNK.sub("", t).strip(" -|:")
    return re.sub(r"\s+", " ", t)[:140]


class GoogleWebDetection:
    name = "google"
    URL = "https://vision.googleapis.com/v1/images:annotate"

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=20)

    def detect(self, jpeg: bytes) -> dict:
        body = {
            "requests": [{
                "image": {"content": base64.b64encode(jpeg).decode()},
                "features": [{"type": "WEB_DETECTION", "maxResults": 12}],
            }]
        }
        r = self.client.post(self.URL, params={"key": self.api_key}, json=body)
        r.raise_for_status()
        resp = r.json()["responses"][0]
        if "error" in resp:
            raise RuntimeError(resp["error"].get("message", "vision api error"))
        return resp.get("webDetection", {})

    @staticmethod
    def candidates(web: dict) -> list[Candidate]:
        out: list[Candidate] = []
        entities = [e for e in web.get("webEntities", []) if e.get("description")]
        tags = [e["description"] for e in entities[:6]]
        for g in web.get("bestGuessLabels", [])[:1]:
            if g.get("label"):
                out.append(Candidate(name=g["label"].strip().title(), source="google",
                                     tags=tags, confidence=0.6))
        seen = {c.name.lower() for c in out}
        for p in web.get("pagesWithMatchingImages", [])[:8]:
            title = clean_title(p.get("pageTitle", ""))
            if len(title) < 4 or title.lower() in seen:
                continue
            seen.add(title.lower())
            # A page that shows the *same* image (full match) is a strong product hit.
            full = bool(p.get("fullMatchingImages"))
            out.append(Candidate(name=title, source="google", url=p.get("url", ""),
                                 tags=tags, confidence=0.8 if full else 0.5))
        return out

    @staticmethod
    def hints(web: dict) -> list[str]:
        h = [g["label"] for g in web.get("bestGuessLabels", []) if g.get("label")]
        h += [e["description"] for e in web.get("webEntities", [])[:8] if e.get("description")]
        h += [clean_title(p.get("pageTitle", "")) for p in web.get("pagesWithMatchingImages", [])[:5]]
        return [x for x in h if x]


CLAUDE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short, specific name a person would search for"},
        "brand": {"type": "string"},
        "model": {"type": "string"},
        "category": {"type": "string", "enum": CATEGORIES},
        "description": {"type": "string", "description": "One or two sentences: what it is, size/material/colour"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "alternatives": {"type": "array", "items": {"type": "string"},
                          "description": "Other plausible names if unsure"},
    },
    "required": ["name", "brand", "model", "category", "description", "tags", "confidence", "alternatives"],
    "additionalProperties": False,
}

CLAUDE_PROMPT = """You're cataloguing the contents of someone's garage storage bins. \
Identify the main object in this photo so it can be found again later by search.

- If it's a recognisable retail product, give the product name, brand and model.
- If it's custom equipment, a part, scrap, or raw material (lumber offcuts, PVC \
pipe, wire, sheet metal…), describe it plainly with dimensions/material if visible.
- Tags: 3–8 lowercase search terms, including the activity it's used for \
(e.g. "camping", "plumbing", "christmas").
- confidence: 0–1, how sure you are of the name.
- Leave brand/model empty rather than guessing.
{hints}"""


def _response_text(resp) -> str:
    """The JSON text block of a structured-output response.

    Tolerates SDK versions that predate newer block types (e.g. the `fallback`
    marker from server-side refusal fallbacks) and surface them as dicts."""
    for b in resp.content:
        kind = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
        if kind == "text":
            return b["text"] if isinstance(b, dict) else b.text
    raise ValueError("no text block in Claude response")


class ClaudeVision:
    name = "claude"

    def __init__(self, api_key: str, model: str):
        import anthropic  # optional dependency; only imported when a key is configured

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def identify(self, jpeg: bytes, hints: list[str] | None = None) -> list[Candidate]:
        hint_text = ""
        if hints:
            hint_text = ("\nA reverse image search returned these (possibly noisy) hints:\n- "
                         + "\n- ".join(hints[:12]))
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.standard_b64encode(jpeg).decode()}},
                    {"type": "text", "text": CLAUDE_PROMPT.format(hints=hint_text)},
                ],
            }],
            # Passed via extra_body so this works across SDK versions (the Pi's
            # nixpkgs-pinned SDK may predate these fields).
            extra_body={
                "fallbacks": "default",
                "output_config": {
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": CLAUDE_SCHEMA},
                },
            },
        )
        if resp.stop_reason == "refusal":
            log.warning("claude declined to identify the image")
            return []
        d = json.loads(_response_text(resp))
        main = Candidate(
            name=d["name"], source="claude", description=d["description"],
            category=d["category"], brand=d["brand"], model=d["model"],
            tags=[t.lower() for t in d["tags"]], confidence=float(d["confidence"]),
        )
        alts = [Candidate(name=a, source="claude", category=d["category"], tags=main.tags,
                          confidence=main.confidence * 0.5) for a in d["alternatives"][:3]]
        return [main, *alts]

    def name_groups(self, groups: list[list[str]]) -> list[str]:
        """Give each cluster of item names a short shelf-label-style title."""
        listing = "\n".join(f"{i}: " + "; ".join(names[:25]) for i, names in enumerate(groups))
        schema = {
            "type": "object",
            "properties": {"names": {"type": "array", "items": {"type": "string"}}},
            "required": ["names"], "additionalProperties": False,
        }
        resp = self.client.beta.messages.create(
            model=self.model, max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            messages=[{"role": "user", "content":
                       "Each numbered line is a cluster of items from a garage inventory. "
                       "Give each cluster a 1-3 word storage-bin title (e.g. \"Camping gear\", "
                       "\"Plumbing parts\"). Return names in the same order.\n\n" + listing}],
            extra_body={"fallbacks": "default",
                        "output_config": {"effort": "low",
                                          "format": {"type": "json_schema", "schema": schema}}},
        )
        if resp.stop_reason == "refusal":
            return []
        return json.loads(_response_text(resp))["names"]


class Identifier:
    def __init__(self, google_key: str, anthropic_key: str, claude_model: str):
        self.google = GoogleWebDetection(google_key) if google_key else None
        self.claude = None
        if anthropic_key:
            try:
                self.claude = ClaudeVision(anthropic_key, claude_model)
            except ImportError:
                log.warning("ANTHROPIC_API_KEY set but the anthropic package is missing")

    @property
    def status(self) -> dict:
        return {"google": self.google is not None, "claude": self.claude is not None}

    def identify(self, jpeg: bytes) -> tuple[list[Candidate], list[str]]:
        """Returns (candidates best-first, provider errors)."""
        cands: list[Candidate] = []
        errors: list[str] = []
        hints: list[str] = []
        if self.google:
            try:
                web = self.google.detect(jpeg)
                cands += self.google.candidates(web)
                hints = self.google.hints(web)
            except Exception as e:  # noqa: BLE001
                log.warning("google web detection failed: %s", e)
                errors.append(f"google: {e}")
        if self.claude:
            try:
                # Claude's answer goes first: it has seen the image AND the
                # Google hints, so it's the best single guess.
                cands = self.claude.identify(jpeg, hints) + cands
            except Exception as e:  # noqa: BLE001
                log.warning("claude identify failed: %s", e)
                errors.append(f"claude: {e}")
        return cands, errors
