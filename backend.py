import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from logic.prompt_templates import SCENE_EDITOR_PROMPT
from logic.analyzer import analyze_scene

app = FastAPI()

# CORS config
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

# Simple in-memory rate limiter
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

# ----- Schemas
class SceneRequest(BaseModel):
    scene: str

class PasswordRequest(BaseModel):
    password: str

# ----- Password gate (matches your frontend POST /validate-password)
@app.post("/validate-password")
async def validate_password(data: PasswordRequest):
    # Embedded password as requested
    ADMIN_PASS = "prantasdatwanta"
    if data.password != ADMIN_PASS:
        raise HTTPException(status_code=403, detail="Access Denied")
    return {"valid": True}

# ----- Analyzer endpoint (used by Analyze button)
@app.post("/analyze")
async def analyze_endpoint(request: Request, data: SceneRequest, x_user_agreement: str = Header(None)):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")
    if not x_user_agreement or x_user_agreement.lower() != "true":
        raise HTTPException(status_code=400, detail="You must accept the Terms & Conditions.")

    # Run analysis (logic kept exactly as in your analyzer.py)
    obj = await analyze_scene(data.scene)
    return {"analysis": obj}

# ----- Editor endpoint (as you pasted; unchanged logic)
@app.post("/edit")
async def edit_scene(request: Request, data: SceneRequest, x_user_agreement: str = Header(None)):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")
    if not x_user_agreement or x_user_agreement.lower() != "true":
        raise HTTPException(status_code=400, detail="You must accept the Terms & Conditions.")

    cleaned = data.scene.strip()
    if len(cleaned) < 30:
        raise HTTPException(status_code=400, detail="Scene too short—please include at least a few lines.")
    if len(cleaned.split()) > 600:
        raise HTTPException(status_code=400, detail="Scene must be two pages or fewer.")

    prompt = SCENE_EDITOR_PROMPT
    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": cleaned}
        ]
    }

    try:
        async with httpx.AsyncClient() as client:
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
            analysis = result["choices"][0]["message"]["content"].strip()
            return {"edit_suggestions": analysis}
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, str(e))

# ----- Static frontend
FRONTEND_DIR = Path(__file__).parent / "frontend_dist"
if not FRONTEND_DIR.exists():
    raise RuntimeError("frontend_dist folder not found.")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# Root
@app.get("/")
async def serve_index():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="index.html not found.")
    return FileResponse(index_path)

# SPA fallback
@app.get("/{full_path:path}")
async def fallback(full_path: str):
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="index.html not found.")
    return FileResponse(index_path)
