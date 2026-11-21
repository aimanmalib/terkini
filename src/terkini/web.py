"""`terkini serve`: the same page as GitHub Pages, served locally by FastAPI (PRD D10).

It serves the page files from docs/ as they are, so the local page and the Pages copy cannot drift apart. Only the
page and its data are served, not the rest of docs/. Host and port come from config/pages.toml [serve]; it holds no key.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from terkini import __version__
from terkini.packs import REPO_ROOT
from terkini.pages import load_pages_config


def create_app(root: Path = REPO_ROOT) -> FastAPI:
    app = FastAPI(title="Terkini", version=__version__, docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "version": __version__}

    cfg = load_pages_config(root)
    out = root / cfg.out_dir
    for name in cfg.serve.files:
        app.add_api_route(f"/{name}", _file(out / name), methods=["GET"], include_in_schema=False)
    app.add_api_route("/", _file(out / "index.html"), methods=["GET"], include_in_schema=False)
    for folder in cfg.serve.folders:
        app.mount(f"/{folder}", StaticFiles(directory=out / folder), name=folder)
    return app


def _file(path: Path):
    def send() -> FileResponse:
        return FileResponse(path)
    return send


def serve(host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    cfg = load_pages_config().serve
    uvicorn.run(create_app(), host=host or cfg.host, port=port or cfg.port, log_level="warning")
