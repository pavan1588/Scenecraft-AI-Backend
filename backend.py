import os, re, time, httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from typing import Optional
from starlette.status import HTTP_429_TOO_MANY_REQUESTS, HTTP_401_UNAUTHORIZED

from logic.analyzer import analyze_scene
from logic.analyzer import STRIP_RE
from logic.prompt_templates import SCENE_EDITOR_PROMPT

# ─── 1. App & Auth Setup ─────────────────────────────────────────────────────
app = FastAPI()
security = HTTPBasic()
ADMIN_USER = "admin"
ADMIN_PASS = os.getenv("ADMIN_PASS", "prantasdatwanta")

def require_auth(creds: HTTPBasicCredentials = Depends(security)):
    if creds.username != ADMIN_USER or creds.password != ADMIN_PASS:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

# ─── 2. CORS ─────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock this to your production domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 3. Health Check ─────────────────────────────────────────────────────────
@app.get("/health")
@app.head("/health")
def health():
    return {"status": "ok"}

# ─── 4. Rate Limiting ────────────────────────────────────────────────────────
RATE_LIMIT = {}
WINDOW, MAX_CALLS = 60, 10

def rate_limiter(ip: str) -> bool:
    now = time.time()
    calls = RATE_LIMIT.setdefault(ip, [])
    RATE_LIMIT[ip] = [t for t in calls if now - t < WINDOW]
    if len(RATE_LIMIT[ip]) >= MAX_CALLS:
        return False
    RATE_LIMIT[ip].append(now)
    return True

# ─── 5. Input Schema ─────────────────────────────────────────────────────────
class SceneRequest(BaseModel):
    scene: str
    
# ─── 6. Scene Analyzer ───────────────────────────────────────────────────────
@app.post("/analyze")
async def analyze(request: Request, data: SceneRequest, x_user_agreement: str = Header(None)):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded.")
    if x_user_agreement != "true":
        raise HTTPException(400, "You must accept the Terms & Conditions.")
    text = data.scene.strip()
    if len(text.split()) < 250:
       raise HTTPException(400, "Scene must be at least one page long (approx. 250 words).")
    if "generate" in text.lower():
       raise HTTPException(400, "SceneCraft AI does not generate scenes. Please submit your own work.")
    result = await analyze_scene(text)

    return {
        "analysis": result["textual_analysis"],
        "visuals": result["visual_insights"]
    }

# ─── 7. Scene Editor ─────────────────────────────────────────────────────────
@app.post("/edit")
async def edit_scene(request: Request, data: SceneRequest, x_user_agreement: str = Header(None)):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(429, "Rate limit exceeded.")

    if x_user_agreement != "true":
        raise HTTPException(400, "You must accept the Terms & Conditions.")

    scene_text = data.scene.strip()
    
    if len(scene_text.split()) < 250:
       raise HTTPException(400, "Scene must be at least one page long (approx. 250 words).")

    if "generate" in scene_text.lower():
       raise HTTPException(400, "SceneCraft AI does not generate scenes. Please submit your own work.")

    # Block generation-style prompts for editor too
    if STRIP_RE.match(scene_text.strip().lower()):
        raise HTTPException(
        status_code=400,
        detail="SceneCraft does not generate scenes. Please submit your own scene or script for editing."
    )

    if len(scene_text.split()) > 650:
        raise HTTPException(400, "Scene (including context) must be under 2 pages.")

    payload = {
        "model": os.getenv("OPENROUTER_MODEL", "gpt-4"),
        "messages": [
            {"role": "system", "content": SCENE_EDITOR_PROMPT},
            {"role": "user", "content": scene_text}
        ]
    }

    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    if not OPENROUTER_API_KEY:
        raise HTTPException(500, "Missing OpenRouter API key.")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            return {
                "edit_suggestions": result["choices"][0]["message"]["content"].strip()
            }
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, str(e))

# ─── 8. Serve Frontend ───────────────────────────────────────────────────────
FRONTEND = Path(__file__).parent / "frontend_dist"
if not FRONTEND.exists():
    raise RuntimeError(f"Frontend build not found: {FRONTEND}")

class PasswordRequest(BaseModel):
    password: str

@app.post("/validate-password")
async def validate_password(data: PasswordRequest):
    expected = os.getenv("SCENECRAFT_PASSWORD", "prantasdatwanta")
    return {"valid": data.password == expected}
    
app.mount("/", StaticFiles(directory="frontend_dist", html=True), name="frontend")
