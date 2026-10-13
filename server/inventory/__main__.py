"""`inventory-server` / `python -m inventory` entry point."""

from __future__ import annotations

import logging


def main() -> None:
    import uvicorn

    from .app import create_app
    from .config import Config

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, proxy_headers=True,
                forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
