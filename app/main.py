"""FastAPI 진입점 — 정적 파일 서빙과 라우터 등록."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.routers import chat, demo, generate, layout, news, reports, rules

VERSION = "0.5.0"

app = FastAPI(title="사내 보고서 취합·편집 에이전트", version=VERSION)
app.mount("/static", StaticFiles(directory=config.STATIC), name="static")
app.mount("/generated", StaticFiles(directory=config.GENERATED), name="generated")

for module in (reports, generate, layout, chat, rules, news, demo):
    app.include_router(module.router)


@app.middleware("http")
async def disable_browser_cache(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    response.headers["X-App-Version"] = VERSION
    return response


@app.get("/")
def index():
    return FileResponse(config.STATIC / "index.html")


@app.get("/health")
def health():
    template = config.active_template()
    return {
        "ok": True,
        "version": VERSION,
        "template": template.name,
        "template_exists": template.exists(),
        "port": int(os.environ.get("PORT", "8020")),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8020")), reload=False)
