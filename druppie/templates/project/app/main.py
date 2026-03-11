"""Application entrypoint."""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings

app = FastAPI(title=settings.app_name)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "app_name": settings.app_name,
    })
