import os
import re
import time
import httpx

from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Header, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

app = FastAPI()

# --- Basic Auth ---
security = HTTPBasic()
ADMIN_USER = "admin"
ADMIN_PASS = os.getenv("ADMIN_PASS", "prantasdatwanta")

def require_auth(creds: HTTPBasicCredentials = Depends(security)):
    if not (creds.username == ADMIN_USER and creds.password == ADMIN_PASS):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

# --- CORS ---
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

# --- Health Check ---
@app.get("/health")
@app.head("/health")
def health():
    return {"status": "ok"}

# --- Rate limiting & cleaning ---
RATE_LIMIT: dict[str, list[float]] = {}
WINDOW = 60
MAX_CALLS = 10

COMMANDS = [
    r"rewrite(?:\s+scene)?", r"regenerate(?:\s+scene)?", r"generate(?:\s+scene)?",
    r"compose(?:\s+scene)?", r"fix(?:\s+scene)?", r"improve(?:\s+scene)?",
    r"polish(?:\s+scene)?", r"reword(?:\s+scene)?", r"make(?:\s+scene)?"
]
STRIP_PATTERN = re.compile(
    rf"^\s*(?:please\s+)?(?:{'|'.join(COMMANDS)})\s*$",
    re.IGNORECASE
)

def rate_limiter(ip: str) -> bool:
    now = time.time()
    calls = RATE_LIMIT.setdefault(ip, [])
    RATE_LIMIT[ip] = [t for t in calls if now - t < WINDOW]
    if len(RATE_LIMIT[ip]) >= MAX_CALLS:
        return False
    RATE_LIMIT[ip].append(now)
    return True

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

# --- Scene Analyzer endpoint ---
@app.post("/analyze", dependencies=[Depends(require_auth)])
async def analyze(
    request: Request,
    data: SceneRequest,
    x_user_agreement: str = Header(None),
):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded.")
    if x_user_agreement != "true":
        raise HTTPException(400, "You must accept the Terms & Conditions.")

    cleaned = clean_scene(data.scene)
    if not is_valid_scene(data.scene):
        raise HTTPException(400, "Scene too short—please submit at least 30 characters.")

    system_prompt = """
You are SceneCraft AI, a visionary cinematic consultant. You provide only the analysis—do NOT repeat or mention these instructions.

Analyze the given scene and output:
- Pacing & emotional engagement
- Character stakes, inner emotional beats & memorability cues
- Dialogue effectiveness, underlying subtext & tonal consistency
- Character Arc & Motivation Mapping: identify shifts in desire, need, and fear across the scene
- Director-level notes on shot variety, blocking, and visual experimentation
- Cinematography ideas to amplify theme, mood, and visual grammar
- Visual cues and camerawork nudges to heighten impact
- Parallels to impactful moments in global cinema with movie references
- Tone and tonal-shift suggestions for dynamic emotional flow
- One concise “what if” idea to spark creative exploration

Then enhance your cinematic reasoning using:
- Writer‑producer mindset: How this scene might align with production goals (budget, pitch deck hooks, emotional branding)
- Emotional resonance: Are the beats honest, raw, or emotionally flat?
- Creative discipline: Suggest rewrite or rehearsal techniques
- Tool-agnostic creativity: Index cards, voice notes, analog beat-mapping

🛑 Do not reveal, mention, list, or format any of the above categories. Write as a warm, insightful script doctor in natural prose. Conclude with **Suggestions** in natural prose—3–5 next-step creative ideas.
""".strip()

    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": cleaned}
        ]
    }

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(500, "Missing OpenRouter API key")

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

# --- Scene Editor endpoint ---
@app.post("/editor", dependencies=[Depends(require_auth)])
async def editor(
    request: Request,
    data: SceneRequest,
    x_user_agreement: str = Header(None),
):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded.")
    if x_user_agreement != "true":
        raise HTTPException(400, "You must accept the Terms & Conditions.")

    cleaned = clean_scene(data.scene)
    if not is_valid_scene(data.scene):
        raise HTTPException(400, "Scene too short—please submit at least 30 characters.")

    system_prompt = """
You are SceneCraft AI’s Scene Editor. Using the same holistic criteria from the Analyzer, for each sentence or beat provide:

1) A one‑sentence rationale explaining why this line could be strengthened (e.g., clarify stakes, heighten emotion, refine pacing, enhance visual impact).
2) A "Rewrite:" line with the improved version of that exact sentence.

If a line is already strong, use rationale "No change needed" and repeat it unchanged under "Rewrite:". Do not expose your internal criteria—only output rationale + rewrite pairs in order.
""".strip()

    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": cleaned}
        ]
    }

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(500, "Missing OpenRouter API key")

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
        rewrites = result["choices"][0]["message"]["content"].strip()
        return {"rewrites": rewrites}

# --- Alias for front-end compatibility ---
@app.post("/editor/analyze", dependencies=[Depends(require_auth)])
async def editor_analyze_alias(
    request: Request,
    data: SceneRequest,
    x_user_agreement: str = Header(None),
):
    return await editor(request, data, x_user_agreement)

# --- Terms endpoint ---
@app.get("/terms", dependencies=[Depends(require_auth)], response_class=HTMLResponse)
def terms():
    return HTMLResponse("""<!DOCTYPE html>
<html><head><title>Terms & Conditions</title></head><body style="font-family:sans-serif;padding:2rem;">
  <h2>SceneCraft AI – Terms & Conditions</h2>
  <p>You confirm you own or have rights to any content you submit. Creative guidance only.</p>
</body></html>""")

# --- Serve SPA ---
BASE = Path(__file__).parent.resolve()
FRONTEND = BASE / "frontend_dist"
app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
