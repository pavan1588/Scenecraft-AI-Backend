from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import HTMLResponse
import httpx
import os
import re
import time
import json
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://scenecraft-AI-frontend.onrender.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SceneRequest(BaseModel):
    scene: str

RATE_LIMIT = {}
ROTATION_THRESHOLD = 50
PASSWORD_USAGE_COUNT = 0
STORED_PASSWORD = os.getenv("SCENECRAFT_PASSWORD", "SCENECRAFT-2024")
PASSWORD_FILE = "scenecraft_password.json"

# Directive patterns to strip
COMMANDS = [
    r"rewrite(?:\s+scene)?",
    r"regenerate(?:\s+scene)?",
    r"generate(?:\s+scene)?",
    r"compose(?:\s+scene)?",
    r"fix(?:\s+scene)?",
    r"improve(?:\s+scene)?",
    r"polish(?:\s+scene)?",
    r"reword(?:\s+scene)?",
    r"make(?:\s+scene)?"
]
_STRIP_PATTERN = re.compile(
    rf"^\s*(?:please\s+)?(?:{'|'.join(COMMANDS)})\s*$",
    flags=re.IGNORECASE
)

def clean_scene_input(text: str) -> str:
    lines = text.splitlines()
    while lines and _STRIP_PATTERN.match(lines[0]):
        lines.pop(0)
    while lines and _STRIP_PATTERN.match(lines[-1]):
        lines.pop(-1)
    return "\n".join(lines).strip()

def is_valid_scene(text: str) -> bool:
    cleaned = clean_scene_input(text)
    return len(cleaned) >= 30

def rate_limiter(ip, window=60, limit=10):
    now = time.time()
    rec = RATE_LIMIT.setdefault(ip, [])
    RATE_LIMIT[ip] = [t for t in rec if now - t < window]
    if len(RATE_LIMIT[ip]) >= limit:
        return False
    RATE_LIMIT[ip].append(now)
    return True

def rotate_password():
    global STORED_PASSWORD, PASSWORD_USAGE_COUNT
    new_token = f"SCENECRAFT-{int(time.time())}"
    STORED_PASSWORD = new_token
    PASSWORD_USAGE_COUNT = 0
    with open(PASSWORD_FILE, "w") as f:
        json.dump({"password": new_token}, f)

@app.post("/analyze")
async def analyze_scene(
    request: Request,
    data: SceneRequest,
    authorization: str = Header(None),
    x_user_agreement: str = Header(None)
):
    global PASSWORD_USAGE_COUNT, STORED_PASSWORD
    ip = request.client.host
    if not rate_limiter(ip):
        raise HTTPException(status_code=HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    if not x_user_agreement or x_user_agreement.lower() != "true":
        raise HTTPException(status_code=400, detail="User agreement must be accepted.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized: missing or invalid token")
    token = authorization.split("Bearer ")[1]
    if token != STORED_PASSWORD:
        raise HTTPException(status_code=403, detail="Forbidden: invalid access token")

    PASSWORD_USAGE_COUNT += 1
    if PASSWORD_USAGE_COUNT >= ROTATION_THRESHOLD:
        rotate_password()

    cleaned_scene = clean_scene_input(data.scene)
    if not is_valid_scene(data.scene):
        return {"error": "Scene too short or invalid. Please submit at least 30 characters for analysis."}

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing OpenRouter API key")

    # Select prompt based on length
    if len(cleaned_scene) < 30:
        prompt = f"""
You are SceneCraft AI, a supportive cinematic consultant.
Provide a concise reflection on imagery, tone, and context without expanding or rewriting.

Snippet:
{cleaned_scene}
### END OF ANALYSIS
"""
    else:
        prompt = f"""
You are SceneCraft AI, a supportive cinematic consultant. Read the scene below and provide deep, focused insights into its core strengths and areas for deeper resonance:
- How pacing governs emotional engagement
- The protagonist's driving stakes and inner emotional beats
- Dialogue effectiveness and underlying subtext
- How cinematography choices might amplify thematic impact
- Parallels to similar impactful scenes in recent Hindi, English, and global cinema
- One concise "what if" idea to spark creative exploration

Finally, include a clear Suggestions section with actionable steps to elevate the scene. Do not rewrite or expand any part of the scene.

Scene:
{cleaned_scene}
### END OF ANALYSIS
"""

    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [{"role": "system", "content": prompt}],
        "stop": ["### END OF ANALYSIS"]
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload
            )
            resp.raise_for_status()
            result = resp.json()
            content = result["choices"][0]["message"]["content"].strip()
            if re.search(r"\bINT\.|\bEXT\.|^\s*[A-Z]{2,}:|CUT TO:", content, flags=re.MULTILINE):
                raise HTTPException(status_code=400, detail="Output rejected: narrative content detected.")
            return {"analysis": content, "notice": "⚠️ For deeper feedback, consider adding more context."}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/terms", response_class=HTMLResponse)
def terms():
    html = """
<!DOCTYPE html>
<html>
  <head><title>SceneCraft - Terms of Use</title></head>
  <body style='font-family: sans-serif; padding: 2rem; max-width: 700px; margin: auto; line-height: 1.6;'>
    <h2>SceneCraft - Legal Terms & Usage Policy</h2>
    <h3>User Agreement</h3>
    <p>By using SceneCraft, you agree to submit only content that you own or are authorized to analyze. This platform is for creative cinematic analysis only.</p>
    <h3>Disclaimer</h3>
    <p>SceneCraft is not a generator. It analyzes your scene using filmmaking and storytelling principles. You remain responsible for submitted content.</p>
    <h3>Usage Policy</h3>
    <ul>
      <li>Submit scenes, monologues, dialogues, or excerpts — not random text or rewrite prompts.</li>
      <li>Do not submit third-party copyrighted material.</li>
      <li>All analysis is creative insight, not legal or factual validation.</li>
    </ul>
    <h3>Copyright Responsibility</h3>
    <p>You are fully responsible for the originality and rights of submitted content. SceneCraft does not store or certify authorship.</p>
    <h3>About SceneCraft</h3>
    <p>SceneCraft helps screenwriters sharpen cinematic storytelling using structure, realism, visual language, psychology, memorability, genre awareness, and creative prompts. It always avoids content generation and focuses on analysis.</p>
    <p style="margin-top: 2rem;"><em>Created for filmmakers, storytellers, and writers who want sharper scenes, not shortcuts.</em></p>
    <hr />
    <p>© SceneCraft 2025. All rights reserved.</p>
  </body>
</html>
"""
    return HTMLResponse(content=html)

@app.get("/")
def root():
    return {"message": "SceneCraft backend is live."}


