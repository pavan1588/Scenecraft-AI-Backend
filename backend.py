import os
import time
import httpx
import re

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.status import HTTP_429_TOO_MANY_REQUESTS
from starlette.responses import HTMLResponse

from logic.analyzer import clean_scene, is_valid_scene, analyze_scene

app = FastAPI()

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

# Rate limiting
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

class SceneRequest(BaseModel):
    scene: str

# Original analyze endpoint
@app.post("/analyze")
async def analyze(request: Request, data: SceneRequest, x_user_agreement: str = Header(None)):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded.")
    if not x_user_agreement or x_user_agreement.lower() != "true":
        raise HTTPException(400, "You must accept the Terms & Conditions.")

    if not is_valid_scene(data.scene):
        raise HTTPException(400, "Scene too short—please submit at least 30 characters.")

    analysis = await analyze_scene(data.scene)
    return {"analysis": analysis}

# New editor/scenario endpoint
@app.post("/editor/analyze")
async def editor_analyze(request: Request, data: SceneRequest, x_user_agreement: str = Header(None)):
    """
    Scene Editor calls this to get both cleaned scene and analysis.
    """
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded.")
    if not x_user_agreement or x_user_agreement.lower() != "true":
        raise HTTPException(400, "You must accept the Terms & Conditions.")

    cleaned = clean_scene(data.scene)
    if not is_valid_scene(data.scene):
        raise HTTPException(400, "Scene too short—please submit at least 30 characters.")
    
    analysis = await analyze_scene(data.scene)
    return {
        "cleaned_scene": cleaned,
        "analysis": analysis
    }

@app.get("/terms", response_class=HTMLResponse)
def terms():
    return HTMLResponse("""<!DOCTYPE html>
<html><head><title>Terms & Conditions</title></head><body style="font-family:sans-serif;padding:2rem;">
  <h2>SceneCraft AI – Terms & Conditions</h2>
  <h3>User Agreement</h3><p>You confirm you own or have rights to any content you submit.</p>
  <h3>Disclaimer</h3><p>Creative guidance only.</p>
  <h3>Usage Policy</h3><ul>
    <li>Original scenes/excerpts only</li>
    <li>No random text or rewrite prompts</li>
    <li>All feedback is creative, not legal advice</li>
  </ul>
  <h3>Copyright</h3><p>You retain all rights; SceneCraft AI does not store content.</p>
  <hr><p>&copy; SceneCraft AI 2025</p>
</body></html>""")

@app.get("/")
def root():
    return {"message": "SceneCraft backend is live."}
