import os, re, time, httpx
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Depends, Header, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

# ─── 1) App & Auth ───────────────────────────────────────────────────────────
app = FastAPI()
security = HTTPBasic()
ADMIN_USER = "admin"
ADMIN_PASS = os.getenv("ADMIN_PASS", "prantasdatwanta")

def require_auth(creds: HTTPBasicCredentials = Depends(security)):
    if creds.username != ADMIN_USER or creds.password != ADMIN_PASS:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )

# ─── 2) CORS for API calls ────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 3) Healthcheck (public) ─────────────────────────────────────────────────
@app.get("/health")
@app.head("/health")
def health():
    return {"status": "ok"}

# ─── 4) Rate‑limit & Cleaning (unchanged) ─────────────────────────────────────
RATE_LIMIT = {}
WINDOW, MAX_CALLS = 60, 10
COMMANDS = [
    r"rewrite(?:\s+scene)?", r"regenerate(?:\s+scene)?", r"generate(?:\s+scene)?",
    r"compose(?:\s+scene)?", r"fix(?:\s+scene)?", r"improve(?:\s+scene)?",
    r"polish(?:\s+scene)?", r"reword(?:\s+scene)?", r"make(?:\s+scene)?"
]
STRIP_RE = re.compile(rf"^\s*(?:please\s+)?(?:{'|'.join(COMMANDS)})\s*$", re.IGNORECASE)

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

# ─── 5) Serve SPA Pages (protected) ──────────────────────────────────────────
FRONTEND = Path(__file__).parent / "frontend_dist"

def serve_file(name: str):
    path = FRONTEND / name
    if not path.exists():
        raise HTTPException(404, "Page not found")
    return FileResponse(path, media_type="text/html")

@app.get("/", dependencies=[Depends(require_auth)])
def home():
    return serve_file("index.html")

@app.get("/editor.html", dependencies=[Depends(require_auth)])
def editor_page():
    return serve_file("editor.html")

@app.get("/how-it-works.html", dependencies=[Depends(require_auth)])
def how_it_works():
    return serve_file("how-it-works.html")

@app.get("/pricing.html", dependencies=[Depends(require_auth)])
def pricing():
    return serve_file("pricing.html")

@app.get("/full-script.html", dependencies=[Depends(require_auth)])
def full_script():
    return serve_file("full-script.html")

@app.get("/terms.html", dependencies=[Depends(require_auth)])
def terms():
    return serve_file("terms.html")

# ─── 6) Static assets ─────────────────────────────────────────────────────────
app.mount("/static", 
          StaticFiles(directory=str(FRONTEND)), 
          name="static")

# ─── 7) Scene Analyzer API ───────────────────────────────────────────────────
@app.post("/analyze")
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

    system_prompt = """<YOUR EXACT ANALYZER PROMPT BLOCK HERE>""".strip()
    payload = {"model":"mistralai/mistral-7b-instruct","messages":[
        {"role":"system","content":system_prompt},
        {"role":"user","content":cleaned}
    ]}
    api_key = os.getenv("OPENROUTER_API_KEY") or HTTPException(500,"Missing API key")
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},
            json=payload
        ); r.raise_for_status()
        result = r.json()["choices"][0]["message"]["content"].strip()
        return JSONResponse({"analysis":result})

# ─── 8) Scene Editor API ─────────────────────────────────────────────────────
@app.post("/editor")
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

    system_prompt = """<YOUR EXACT EDITOR PROMPT BLOCK HERE>""".strip()
    payload = {"model":"mistralai/mistral-7b-instruct","messages":[
        {"role":"system","content":system_prompt},
        {"role":"user","content":cleaned}
    ]}
    api_key = os.getenv("OPENROUTER_API_KEY") or HTTPException(500,"Missing API key")
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},
            json=payload
        ); r.raise_for_status()
        result = r.json()["choices"][0]["message"]["content"].strip()
        return JSONResponse({"rewrites":result})
