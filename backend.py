import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from logic.prompt_templates import SCENE_EDITOR_PROMPT
from logic.analyzer import analyze_scene  # ensure file exists at logic/analyzer.py
import httpx

app = FastAPI()  # MUST be top-level

# CORS
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

# Simple rate limit
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

# Models
class SceneRequest(BaseModel):
    scene: str

class PasswordRequest(BaseModel):
    password: str

# Health
@app.get("/health")
def health():
    return {"status": "ok"}

# Password gate (HTML calls this)
@app.post("/validate-password")
def validate_password(payload: PasswordRequest):
    expected = os.getenv("ADMIN_PASS", "").strip()
    ok = bool(expected) and (payload.password == expected)
    return {"valid": ok}

# Analyzer (HTML calls this)
@app.post("/analyze")
async def analyze_api(request: Request, data: SceneRequest, x_user_agreement: str = Header(None)):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")
    if not x_user_agreement or x_user_agreement.lower() != "true":
        raise HTTPException(status_code=400, detail="You must accept the Terms & Conditions.")
    result = await analyze_scene(data.scene)
    return {"analysis": result}

# Editor (your original, with 180s timeout)
@app.post("/edit")
async def edit_scene(request: Request, data: SceneRequest, x_user_agreement: str = Header(None)):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")
    if not x_user_agreement or x_user_agreement.lower() != "true":
        raise HTTPException(status_code=400, detail="You must accept the Terms & Conditions.")

    cleaned = (data.scene or "").strip()
    if len(cleaned) < 30:
        raise HTTPException(status_code=400, detail="Scene too short—please include at least a few lines.")
    if len(cleaned.split()) > 600:
        raise HTTPException(status_code=400, detail="Scene must be two pages or fewer.")

    payload = {
        "model": os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct"),
        "messages": [
            {"role": "system", "content": SCENE_EDITOR_PROMPT},
            {"role": "user", "content": cleaned}
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            resp.raise_for_status()
            result = resp.json()
            analysis = (result["choices"][0]["message"]["content"] or "").strip()
            return {"edit_suggestions": analysis}
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, str(e))

# Frontend serving (no import-time crash if folder missing)
FRONTEND_DIR = Path(__file__).parent / "frontend_dist"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    async def serve_index():
        idx = FRONTEND_DIR / "index.html"
        if not idx.exists():
            raise HTTPException(status_code=500, detail="index.html not found.")
        return FileResponse(idx)

    @app.get("/{full_path:path}")
    async def fallback(full_path: str):
        idx = FRONTEND_DIR / "index.html"
        if not idx.exists():
            raise HTTPException(status_code=500, detail="index.html not found.")
        return FileResponse(idx)
else:
    @app.get("/")
    def frontend_missing():
        return JSONResponse({"status": "ok", "note": "frontend_dist not found on server"}, 200)
