"""Runtime configuration, all from environment variables.

The server is deployed as a systemd unit on the garage Pi (see deploy/nix), where
secrets (API keys) arrive via an EnvironmentFile dropped out of band; locally the
same variables can simply be exported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() not in ("0", "false", "no", "off")


@dataclass(frozen=True)
class Config:
    data_dir: Path
    # Base URL encoded into bin-label QR codes (e.g. https://garage.tail1234.ts.net).
    # Empty = derive from the request that triggered the print.
    public_url: str
    printd_url: str
    web_dir: Path | None
    google_vision_api_key: str
    anthropic_api_key: str
    claude_model: str
    embed_enabled: bool
    model_base_url: str
    label_font: str
    host: str
    port: int
    extra: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "inventory.db"

    @property
    def photo_dir(self) -> Path:
        return self.data_dir / "photos"

    @property
    def model_dir(self) -> Path:
        return self.data_dir / "models"

    @staticmethod
    def from_env() -> "Config":
        web = os.environ.get("INVENTORY_WEB_DIR", "")
        if not web:
            # Dev default: the sibling web/ build output, if it exists.
            cand = Path(__file__).resolve().parents[2] / "web" / "dist"
            web = str(cand) if cand.is_dir() else ""
        return Config(
            data_dir=Path(os.environ.get("INVENTORY_DATA_DIR", "./data")).resolve(),
            public_url=os.environ.get("INVENTORY_PUBLIC_URL", "").rstrip("/"),
            printd_url=os.environ.get("INVENTORY_PRINTD_URL", "http://127.0.0.1:8631").rstrip("/"),
            web_dir=Path(web) if web else None,
            google_vision_api_key=os.environ.get("GOOGLE_VISION_API_KEY", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            claude_model=os.environ.get("INVENTORY_CLAUDE_MODEL", "claude-opus-5-5"),
            embed_enabled=_flag("INVENTORY_EMBED", True),
            model_base_url=os.environ.get(
                "INVENTORY_MODEL_URL",
                "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main",
            ).rstrip("/"),
            label_font=os.environ.get("INVENTORY_LABEL_FONT", ""),
            host=os.environ.get("INVENTORY_HOST", "0.0.0.0"),
            port=int(os.environ.get("INVENTORY_PORT", "8080")),
        )
