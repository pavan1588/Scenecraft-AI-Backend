import os, re, time, httpx
from pathlib import Path

from fastapi import (
    FastAPI, Request, HTTPException,
    Depends, status
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from logic.analyzer import analyze_scene  # ← your existing analyzer logic here

# ─── APP & AUTH ─────────────────────────────────────────────────────────
app = FastAPI()
security = HTTPBasic()
ADMIN_USER = "admin"
ADMIN_PASS = os.getenv("ADMIN_PASS", "prantasdatwanta")

def require_auth(creds: HTTPBasicCredentials = Depends(security)):
    if creds.username != ADMIN_USER or creds.password != ADMIN_PASS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

# ─── HEALTHCHECK ────────────────────────────────────────────────────────
@app.get("/health")
@app.head("/health")
def health():
    return {"status": "ok"}

# ─── RATE LIMIT & CLEAN ─────────────────────────────────────────────────
RATE_LIMIT = {}
WINDOW, MAX_CALLS = 60, 10
STRIP_RE = re.compile(r"^\s*(?:please\s+)?(?:rewrite|regenerate|generate|compose|fix|improve|polish|reword|make)(?:\s+scene)?\s*$", re.IGNORECASE)

def rate_limiter(ip: str) -> bool:
    now = time.time()
    calls = RATE_LIMIT.setdefault(ip, [])
    # purge old
    RATE_LIMIT[ip] = [t for t in calls if now - t < WINDOW]
    if len(RATE_LIMIT[ip]) >= MAX_CALLS:
        return False
    RATE_LIMIT[ip].append(now)
    return True

def clean_scene(text: str) -> str:
    lines = text.splitlines()
    while lines and STRIP_RE.match(lines[0]):
        lines.pop(0)
    while lines and STRIP_RE.match(lines[-1]):
        lines.pop(-1)
    return "\n".join(lines).strip()

def is_valid_scene(text: str) -> bool:
    return len(clean_scene(text)) >= 30

class SceneRequest(BaseModel):
    scene: str

# ─── SCENE ANALYZER ─────────────────────────────────────────────────────
@app.post("/analyze", dependencies=[Depends(require_auth)])
async def analyze_endpoint(req: SceneRequest, request: Request):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(429, "Rate limit exceeded.")
    cleaned = clean_scene(req.scene)
    if not is_valid_scene(cleaned):
        raise HTTPException(400, "Scene too short—please submit at least 30 characters.")
    # call into your existing analyzer logic
    result = analyze_scene(cleaned)
    return JSONResponse({"analysis": result})


# ─── SCENE EDITOR ────────────────────────────────────────────────────────
@app.post("/editor", dependencies=[Depends(require_auth)])
async def editor_endpoint(req: SceneRequest, request: Request):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(429, "Rate limit exceeded.")
    cleaned = clean_scene(req.scene)
    if not is_valid_scene(cleaned):
        raise HTTPException(400, "Scene too short—please submit at least 30 characters.")
    # here you’d call your editor logic (presumably in logic/analyzer.py or another module)
    # e.g. `rewrite = edit_scene(cleaned)`
    # but if it’s inline with the same analyzer.py, just import & call
    result = analyze_scene(  # ← replace with your actual editor function
        cleaned, mode="editor"
    )
    return JSONResponse({"rewrites": result})


# ─── SERVE YOUR SPA ──────────────────────────────────────────────────────
FRONTEND = Path(__file__).parent / "frontend_dist"
if not FRONTEND.exists():
    raise RuntimeError(f"Front‑end build not found at {FRONTEND}")

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def serve_index():
    return HTMLResponse((FRONTEND / "index.html").read_text(), status_code=200)
