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

# In-memory rate limiting per IP
RATE_LIMIT = {}
WINDOW = 60  # seconds
MAX_CALLS = 10

def rate_limiter(ip: str) -> bool:
    now = time.time()
    calls = RATE_LIMIT.setdefault(ip, [])
    # purge old
    RATE_LIMIT[ip] = [t for t in calls if now - t < WINDOW]
    if len(RATE_LIMIT[ip]) >= MAX_CALLS:
        return False
    RATE_LIMIT[ip].append(now)
    return True

# Clean-up patterns for directive lines
COMMANDS = [r"rewrite(?:\s+scene)?", r"regenerate(?:\s+scene)?", r"generate(?:\s+scene)?",
            r"compose(?:\s+scene)?", r"fix(?:\s+scene)?", r"improve(?:\s+scene)?",
            r"polish(?:\s+scene)?", r"reword(?:\s+scene)?", r"make(?:\s+scene)?"]
STRIP_PATTERN = re.compile(rf"^\s*(?:please\s+)?(?:{'|'.join(COMMANDS)})\s*$", re.IGNORECASE)

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

@app.post("/analyze")
async def analyze(request: Request, data: SceneRequest, x_user_agreement: str = Header(None)):
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded. Try again later.")
    if not x_user_agreement or x_user_agreement.lower() != "true":
        raise HTTPException(400, "You must accept the Terms & Conditions (x-user-agreement header).")

    cleaned = clean_scene(data.scene)
    if not is_valid_scene(data.scene):
        raise HTTPException(400, "Scene too short—please submit at least 30 characters.")

    # Enhanced prompt with memorability cues, director-level notes, experimentation ideas, etc.
    prompt = f"""
You are SceneCraft AI, a visionary cinematic consultant. After reading the scene, provide:

• Pacing & emotional engagement  
• Character stakes, inner emotional beats & memorability cues  
• Dialogue effectiveness, underlying subtext & tonal consistency  
• Director-level notes on shot variety, blocking, and visual experimentation  
• Cinematography ideas to amplify theme, mood, and visual grammar  
• Visual cues and camerawork nudges to heighten impact  
• Parallels to impactful moments in global cinema with movie references  
• Tone and tonal-shift suggestions for dynamic emotional flow  
• One concise “what if” idea to spark creative exploration  

Finally, include a Suggestions section with next-step experiments (e.g. non-linear edits, color motif play, subtext through silence, dynamic camera movement, etc.).

Scene:
{cleaned}
""".strip()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(500, "Missing OpenRouter API key")

    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [{"role": "system", "content": prompt}],
        "stop": ["Scene:"]
    }

    try:
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
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/terms", response_class=HTMLResponse)
def terms():
    return HTMLResponse(
"""
<!DOCTYPE html><html><head><title>Terms & Conditions</title></head><body style="font-family:sans-serif; padding:2rem;">
  <h2>SceneCraft AI – Terms & Conditions</h2>
  <h3>User Agreement</h3>
  <p>By using this service, you confirm you own or have rights to any content you submit.</p>
  <h3>Disclaimer</h3>
  <p>Analysis is provided for creative guidance. You remain responsible for all content and usage.</p>
  <h3>Usage Policy</h3>
  <ul>
    <li>Submit only original scenes or authorized excerpts.</li>
    <li>No random text or rewrite prompts.</li>
    <li>All feedback is creative, not legal advice.</li>
  </ul>
  <h3>Copyright Responsibility</h3>
  <p>You retain all rights to your submissions; SceneCraft AI does not store or certify ownership.</p>
  <hr><p>&copy; SceneCraft AI 2025.</p>
</body></html>
"""
    )

@app.get("/")
def root():
    return {"message": "SceneCraft backend is live."}
