"""`terkini serve`: the same page as GitHub Pages, served locally by FastAPI (PRD D10).

It serves the page files from docs/ as they are, so the local page and the Pages copy cannot drift apart. Only the
page and its data are served, not the rest of docs/. Host and port come from config/pages.toml [serve].

`POST /api/check` checks one answer and returns the report as JSON (PRD §1 users 1). It follows the CLI mode rule
(terkini.service): replay with no TAVILY_API_KEY, live with your own keys from the environment or .env. Live mode spends
your credits, so the server listens on 127.0.0.1 by default; do not expose it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from terkini import __version__
from terkini.packs import REPO_ROOT
from terkini.pages import load_pages_config
from terkini.service import NoRecording, UnknownPack, load_api_config, run


class CheckRequest(BaseModel):
    answer: str = Field("", description="the AI answer to check; in replay mode, a recorded answer")
    pack: str | None = Field(None, description="country pack in packs/ (default from config/api.toml)")
    case: str | None = Field(None, description="replay this recorded run by name")


def create_app(root: Path = REPO_ROOT) -> FastAPI:
    app = FastAPI(title="Terkini", version=__version__, docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "version": __version__}

    api = load_api_config(root)

    @app.post("/api/check")
    def check(req: CheckRequest) -> dict:
        from terkini.gateway import GatewayNotConfigured

        if not req.answer.strip() and not req.case:
            raise HTTPException(422, "give 'answer' (or 'case' to replay a recorded run)")
        if len(req.answer) > api.max_answer_chars:
            raise HTTPException(413, f"answer is longer than {api.max_answer_chars} characters")
        pack = req.pack or api.default_pack
        try:
            out = run(req.answer, pack=pack, case=req.case, root=root)
        except UnknownPack:
            raise HTTPException(400, f"no pack {pack!r} in packs/") from None
        except NoRecording:
            raise HTTPException(404, "replay mode (no TAVILY_API_KEY on the server) checks recorded runs only: "
                                     "send a recorded answer or 'case', or start the server with your own keys") from None
        except GatewayNotConfigured as e:
            raise HTTPException(503, f"live mode needs the Bifrost gateway: {e}") from None
        return {"mode": out.mode, "pack": pack, **out.report.model_dump(mode="json")}

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

    from terkini.gateway import load_env_file

    load_env_file(REPO_ROOT / ".env")
    cfg = load_pages_config().serve
    uvicorn.run(create_app(), host=host or cfg.host, port=port or cfg.port, log_level="warning")
