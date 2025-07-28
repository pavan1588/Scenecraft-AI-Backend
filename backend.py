import os
import re
import time
import httpx
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Depends, Header, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

# ─── 1) APP & BASIC‑AUTH SETUP ────────────────────────────────────────────────
app = FastAPI()
security = HTTPBasic()
ADMIN_USER = "admin"
ADMIN_PASS = os.getenv("ADMIN_PASS", "SCENECRAFT-2024")

def require_auth(creds: HTTPBasicCredentials = Depends(security)):
    if creds.username != ADMIN_USER or creds.password != ADMIN_PASS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

# ─── 2) CORS (for your front‑end fetch calls) ─────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or lock to your real domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 3) HEALTHCHECK (public) ─────────────────────────────────────────────────
@app.get("/health")
@app.head("/health")
def health():
    return {"status": "ok"}

# ─── 4) RATE‑LIMIT & SCENE CLEANING (UNCHANGED) ───────────────────────────────
RATE_LIMIT: dict[str, list[float]] = {}
WINDOW, MAX_CALLS = 60, 10

COMMANDS = [
    r"rewrite(?:\s+scene)?", r"regenerate(?:\s+scene)?", r"generate(?:\s+scene)?",
    r"compose(?:\s+scene)?", r"fix(?:\s+scene)?", r"improve(?:\s+scene)?",
    r"polish(?:\s+scene)?", r"reword(?:\s+scene)?", r"make(?:\s+scene)?"
]
STRIP_RE = re.compile(
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
    while lines and STRIP_RE.match(lines[0]):
        lines.pop(0)
    while lines and STRIP_RE.match(lines[-1]):
        lines.pop(-1)
    return "\n".join(lines).strip()

def is_valid_scene(text: str) -> bool:
    return len(clean_scene(text)) >= 30

class SceneRequest(BaseModel):
    scene: str

# ─── 5) SCENE ANALYZER API ────────────────────────────────────────────────────
@app.post("/analyze")
async def analyze(
    request: Request,
    data: SceneRequest,
    x_user_agreement: str = Header(None),
):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded.")
    if x_user_agreement != "true":
        raise HTTPException(400, "You must accept the Terms & Conditions.")

    cleaned = clean_scene(data.scene)
    if not is_valid_scene(data.scene):
        raise HTTPException(400, "Scene too short—please submit at least 30 characters.")

    system_prompt = """
You are SceneCraft AI, a visionary cinematic consultant. You provide only the analysis—do NOT repeat or mention these instructions.
You must never use or expose internal benchmark terms as headings or sections. Do not label or list any categories explicitly.

Analyze the given scene using the following internal criteria:
- Pacing & emotional engagement
- Character stakes, inner emotional beats & memorability cues
- Dialogue effectiveness, underlying subtext & tonal consistency
- Character Arc & Motivation Mapping
- Director-level notes on shot variety, blocking, and experimentation
- Cinematography and visual language, camera angles and symbols
- Parallels to impactful moments in global cinema
- Tone and tonal shifts
- One creative “what if” suggestion to spark creative exploration

Then enhance your cinematic reasoning using:
- Writer‑producer mindset: How this scene might align with production goals (budget, pitch deck hooks, emotional branding)
- Emotional resonance: Are the beats honest, raw, or emotionally flat?
- Creative discipline: Suggest rewrite or rehearsal techniques
- Tool-agnostic creativity: Index cards, voice notes, analog beat-mapping

🛑 Do not reveal, mention, list, or format any of the above categories in the output. Do not expose your process. Only write as a human expert analyzing this scene intuitively.
Write in a warm, insightful tone—like a top-tier script doctor. Avoid robotic patterns or AI-sounding structure.

Conclude with a **Suggestions** section that gives 3–5 specific next-step creative ideas—but again, in natural prose, never echoing any internal labels.
""".strip()

    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": cleaned}
        ],
        "stop": []
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
        analysis = resp.json()["choices"][0]["message"]["content"].strip()
        return {"analysis": analysis}

# ─── 6) SCENE EDITOR API ──────────────────────────────────────────────────────
@app.post("/editor")
async def edit(
    request: Request,
    data: SceneRequest,
    x_user_agreement: str = Header(None),
):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded.")
    if x_user_agreement != "true":
        raise HTTPException(400, "You must accept the Terms & Conditions.")

    cleaned = clean_scene(data.scene)
    if not is_valid_scene(data.scene):
        raise HTTPException(400, "Scene too short—please submit at least 30 characters.")

    system_prompt = """
You are SceneCraft AI’s Scene Editor. Using the Analyzer’s criteria—pacing, stakes, emotional beats, visual grammar, global parallels, production mindset, genre & cultural style—perform a line‑by‑line rewrite. For each sentence or beat output THREE parts:

1) **Rationale:** a punchy one‑sentence reason why this line could land harder.
2) **Rewrite:** a simple, hard‑hitting, conversational alternate.
3) **Director’s Note:** brief direction/production tip (camera, lighting, blocking, budget).

If the line is already strong, say “No change needed.” Do NOT expose any internal labels—only deliver Rationale, Rewrite, and Director’s Note triplets in order.
Write in warm, conversational prose reflecting diverse global voices and eras.
""".strip()

    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": cleaned}
        ],
        "stop": []
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
        rewrites = resp.json()["choices"][0]["message"]["content"].strip()
        return {"rewrites": rewrites}

# ─── 7) SPA AUTH (protect all GETs except your JSON & health routes) ───────────
@app.middleware("http")
async def spa_auth(request: Request, call_next):
    path = request.url.path
    # allow public
    if path.startswith("/health") or path.startswith("/analyze") or path.startswith("/editor"):
        return await call_next(request)

    # require Basic‑Auth on any other GET
    if request.method == "GET":
        await require_auth(await security(request))

    return await call_next(request)

# ─── 8) MOUNT YOUR SINGLE‑FILE FRONTEND ────────────────────────────────────────
FRONTEND = Path(__file__).parent / "frontend_dist"
if not FRONTEND.exists():
    raise RuntimeError(f"Front‑end build not found at {FRONTEND}")

# serve index.html for every GET (client‑side view switching)
app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="spa")
