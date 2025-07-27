import os
import re
import time
import httpx
import base64
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from pydantic import BaseModel

app = FastAPI()

# ---- HEALTH CHECK (unprotected) ----
@app.get("/health")
def health():
    return {"status": "ok"}

# ---- GLOBAL BASIC‑AUTH MIDDLEWARE ----
ADMIN_USER = "admin"
ADMIN_PASS = os.getenv("ADMIN_PASS", "prantasdatwanta")

def _check_auth(header: str) -> bool:
    """Validate Basic auth header."""
    try:
        scheme, b64 = header.split(" ", 1)
        if scheme.lower() != "basic":
            return False
        user_pass = base64.b64decode(b64).decode()
        user, pw = user_pass.split(":",1)
        return user == ADMIN_USER and pw == ADMIN_PASS
    except Exception:
        return False

@app.middleware("http")
async def enforce_basic_auth(request: Request, call_next: Callable):
    # allow health and openapi docs through without auth
    if request.url.path in ("/health", "/openapi.json", "/docs", "/docs/oauth2-redirect"):
        return await call_next(request)

    hdr = request.headers.get("Authorization")
    if not hdr or not _check_auth(hdr):
        return PlainTextResponse(
            "Unauthorized",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"}
        )

    return await call_next(request)


# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://scenecraft-ai.com",
        "https://www.scenecraft-ai.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- STATIC FRONTEND SERVING ----
BASE = Path(__file__).parent
FRONTEND = BASE / "frontend_dist"

app.mount("/static", 
    FileResponse if False else # dummy to satisfy import
    (), name="static"
)
# Instead of using StaticFiles (which bypasses our middleware), we'll serve manually:

@app.get("/", response_class=FileResponse)
def serve_index():
    idx = FRONTEND / "index.html"
    if not idx.is_file():
        raise HTTPException(500, "index.html not found")
    return FileResponse(str(idx))

@app.get("/editor.html", response_class=FileResponse)
def serve_editor():
    ed = FRONTEND / "editor.html"
    if not ed.is_file():
        raise HTTPException(500, "editor.html not found")
    return FileResponse(str(ed))

@app.get("/static/{file_path:path}")
def serve_static(file_path: str):
    sf = FRONTEND / file_path
    if not sf.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(str(sf))

# Stub routes for extra tabs
@app.get("/brief", response_class=HTMLResponse)
def brief():
    return "<h1>SceneCraft AI – Brief</h1><p>Coming soon…</p>"

@app.get("/fullscript", response_class=HTMLResponse)
def full_script():
    return "<h1>SceneCraft AI – Full Script Writer</h1><p>Coming soon…</p>"

@app.get("/how", response_class=HTMLResponse)
def how_it_works():
    return "<h1>How it Works</h1><p>Coming soon…</p>"

@app.get("/pricing", response_class=HTMLResponse)
def pricing():
    return "<h1>Pricing</h1><p>Coming soon…</p>"

# ---- RATE LIMITING & SCENE LOGIC ----
RATE_LIMIT: dict[str, list[float]] = {}
WINDOW = 60
MAX_CALLS = 10

def rate_limiter(ip: str) -> bool:
    now = time.time()
    calls = RATE_LIMIT.setdefault(ip, [])
    RATE_LIMIT[ip] = [t for t in calls if now - t < WINDOW]
    if len(RATE_LIMIT[ip]) >= MAX_CALLS:
        return False
    RATE_LIMIT[ip].append(now)
    return True

COMMANDS = [
    r"rewrite(?:\s+scene)?", r"regenerate(?:\s+scene)?", r"generate(?:\s+scene)?",
    r"compose(?:\s+scene)?", r"fix(?:\s+scene)?", r"improve(?:\s+scene)?",
    r"polish(?:\s+scene)?", r"reword(?:\s+scene)?", r"make(?:\s+scene)?"
]
STRIP_PATTERN = re.compile(
    rf"^\s*(?:please\s+)?(?:{'|'.join(COMMANDS)})\s*$",
    re.IGNORECASE
)

def clean_scene(text: str) -> str:
    lines = text.splitlines()
    while lines and STRIP_PATTERN.match(lines[0]):
        lines.pop(0)
    while lines and STRIP_PATTERN.match(lines[-1]):
        lines.pop(-1)
    return "\n".join(lines).strip()

def is_valid_scene(text: str) -> bool:
    return len(clean_scene(text)) >= 30

class SceneRequest(BaseModel):
    scene: str

# ---- ANALYZE ENDPOINT ----
@app.post("/analyze")
async def analyze(
    request: Request,
    data: SceneRequest,
    x_user_agreement: str = Header(None)
):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded.")
    if not x_user_agreement or x_user_agreement.lower() != "true":
        raise HTTPException(400, "You must accept the Terms & Conditions.")

    cleaned = clean_scene(data.scene)
    if not is_valid_scene(data.scene):
        raise HTTPException(400, "Scene too short—please submit at least 30 characters.")

    system_prompt = """… (your full prompt unchanged) …"""

    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": cleaned}
        ],
        "stop": []
    }

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(500, "Missing OpenRouter API key")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            resp.raise_for_status()
            result = resp.json()
            analysis = result["choices"][0]["message"]["content"].strip()
            return {"analysis": analysis}
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, str(e))

# ---- EDITOR ANALYZE (alias) ----
@app.post("/editor/analyze")
async def editor_analyze(
    request: Request,
    data: SceneRequest,
    x_user_agreement: str = Header(None)
):
    return await analyze(request, data, x_user_agreement)

# ---- TERMS & CONDITIONS ----
@app.get("/terms", response_class=HTMLResponse)
def terms():
    return HTMLResponse("""<!DOCTYPE html>
<html><head><title>Terms & Conditions</title></head><body style="font-family:sans-serif;padding:2rem;">
  <h2>SceneCraft AI – Terms & Conditions</h2>
  … same content …
</body></html>""")
