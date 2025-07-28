import os, re, time, httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from starlette.status import HTTP_429_TOO_MANY_REQUESTS, HTTP_401_UNAUTHORIZED

from logic.analyzer import analyze_scene
from logic.prompt_templates import SCENE_EDITOR_PROMPT

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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HEALTHCHECK
@app.head("/health")
def health():
    return {"status": "ok"}

# RATE LIMITING
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

# ===== SCENE ANALYZER =====
class SceneRequest(BaseModel):
    scene: str

@app.post("/analyze")
async def analyze(request: Request, data: SceneRequest, x_user_agreement: str = Header(None)):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded.")
    if x_user_agreement != "true":
        raise HTTPException(400, "You must accept the Terms & Conditions.")
    text = data.scene.strip()
    if len(text) < 30:
        raise HTTPException(400, "Scene too short—please enter at least 30 characters.")
    return {"analysis": await analyze_scene(text)}

# ===== SCENE EDITOR =====
@app.post("/edit")
async def edit_scene(request: Request, data: SceneRequest, x_user_agreement: str = Header(None)):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(429, "Rate limit exceeded.")
    if x_user_agreement != "true":
        raise HTTPException(400, "You must accept the Terms & Conditions.")
    cleaned = data.scene.strip()
    if len(cleaned) < 30:
        raise HTTPException(400, "Scene too short.")
    if len(cleaned.split()) > 600:
        raise HTTPException(400, "Scene must be 2 pages or fewer.")

    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "system", "content": SCENE_EDITOR_PROMPT},
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
            return {"edit_suggestions": result["choices"][0]["message"]["content"].strip()}
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, str(e))

# Serve Frontend
FRONTEND = Path(__file__).parent / "frontend_dist"
if not FRONTEND.exists():
    raise RuntimeError(f"Frontend build not found: {FRONTEND}")
    @app.get("/health")
def health_check():
    return {"status": "ok"}

app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="spa")
