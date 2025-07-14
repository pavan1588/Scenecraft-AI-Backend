from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os, re, time, httpx
from starlette.status import HTTP_429_TOO_MANY_REQUESTS
from starlette.responses import HTMLResponse

app = FastAPI()

# CORS: allow your frontend domains
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

# In‑memory rate limiting per IP\RATE_LIMIT = {}
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

# Cleanup patterns\COMMANDS = [...]
STRIP_PATTERN = re.compile(rf"^\s*(?:please\s+)?(?:{'|'.join(COMMANDS)})\s*$", re.IGNORECASE)

def clean_scene(text: str) -> str:
    lines = text.splitlines()
    while lines and STRIP_PATTERN.match(lines[0]): lines.pop(0)
    while lines and STRIP_PATTERN.match(lines[-1]): lines.pop(-1)
    return "\n".join(lines).strip()

def is_valid_scene(text: str) -> bool:
    return len(clean_scene(text)) >= 30

class SceneRequest(BaseModel):
    scene: str

@app.post("/analyze")
async def analyze(request: Request, data: SceneRequest, x_user_agreement: str = Header(None)):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded.")
    if not x_user_agreement or x_user_agreement.lower() != "true":
        raise HTTPException(400, "Accept the Terms & Conditions.")

    cleaned = clean_scene(data.scene)
    if not is_valid_scene(data.scene):
        raise HTTPException(400, "Scene too short (min 30 chars).")

    # Enhanced prompt (unchanged logic)
    prompt = f"""
You are SceneCraft AI, a visionary cinematic consultant. After reading the scene, provide:
• Pacing & engagement
• Character stakes, inner beats & memorability cues
• Dialogue subtext & tonal consistency
• Director‑level notes on blocking & experimentation
• Cinematography grammar & visual cues
• Camerawork nudges & tone shifts
• Movie references & parallels
• One concise "what if" idea

Suggestions: next steps and experiments.

Scene:
{cleaned}
""".strip()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(500, "Missing API key")

    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [{"role":"system","content":prompt}],
        "stop": ["Scene:"]
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type":"application/json"},
                json=payload
            )
            resp.raise_for_status()
            result = resp.json()
            return {"analysis": result["choices"][0]["message"]["content"].strip()}
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/terms", response_class=HTMLResponse)
def terms():
    return HTMLResponse("""
<!DOCTYPE html><html><head><title>Terms & Conditions</title></head><body style='padding:2rem;font-family:sans-serif;'>
<h2>Terms & Conditions</h2>
<h3>User Agreement</h3><p>Submit only content you own or have rights to.</p>
<h3>Disclaimer</h3><p>Creative analysis only; you are responsible for use.</p>
<h3>Usage Policy</h3><ul><li>Original scenes/excerpts only</li><li>No random text</li><li>Not legal advice</li></ul>
<h3>Copyright</h3><p>You retain all rights; we don't store or certify ownership.</p>
<hr><p>&copy; SceneCraft AI 2025</p>
</body></html>
""
)

@app.get("/")
def root(): return {"message":"Live"}
