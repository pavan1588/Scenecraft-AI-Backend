from __future__ import annotations
import os
import re
import time
import json
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import HTMLResponse
from starlette.status import HTTP_429_TOO_MANY_REQUESTS
import httpx

app = FastAPI()

# CORS: allow your frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://scenecraft-ai.com",
        "https://www.scenecraft-ai.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in‐memory rate limiting by IP
RATE_LIMIT: dict[str, list[float]] = {}
RATE_WINDOW = 60  # seconds
RATE_CALLS = 10   # calls per window

def rate_limiter(ip: str, window: int = RATE_WINDOW, limit: int = RATE_CALLS) -> bool:
    now = time.time()
    rec = RATE_LIMIT.setdefault(ip, [])
    # drop old timestamps
    RATE_LIMIT[ip] = [t for t in rec if now - t < window]
    if len(RATE_LIMIT[ip]) >= limit:
        return False
    RATE_LIMIT[ip].append(now)
    return True

# Scene‐cleaning patterns
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

class SceneRequest(BaseModel):
    scene: str

@app.post("/analyze")
async def analyze_scene(
    request: Request,
    data: SceneRequest,
    x_user_agreement: str = Header(None),
):
    ip = request.client.host
    # rate limit
    if not rate_limiter(ip):
        raise HTTPException(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later."
        )
    # must accept terms
    if not x_user_agreement or x_user_agreement.lower() != "true":
        raise HTTPException(
            status_code=400,
            detail="You must accept the Terms & Conditions (x-user-agreement header = true)."
        )
    # clean & validate
    cleaned = clean_scene_input(data.scene)
    if not is_valid_scene(data.scene):
        raise HTTPException(
            status_code=400,
            detail="Scene too short or invalid. Submit at least 30 characters."
        )

    # choose prompt
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
{cleaned}
""".strip()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(500, detail="Missing OpenRouter API key")

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
            content = result["choices"][0]["message"]["content"].strip()
            # rudimentary check to avoid narrative generation
            if re.search(r"\bINT\.|\bEXT\.|CUT TO:|^[A-Z]{2,}:", content, flags=re.MULTILINE):
                raise HTTPException(400, detail="Output rejected: narrative content detected.")
            return {"analysis": content}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/terms", response_class=HTMLResponse)
def terms():
    # your existing detailed terms & conditions HTML
    html = """
<!DOCTYPE html>
<html>
  <head><title>SceneCraft – Legal Terms & Usage Policy</title></head>
  <body style='font-family: sans-serif; padding: 2rem; max-width: 700px; margin: auto;'>
    <h2>SceneCraft – Terms of Use</h2>
    <h3>User Agreement</h3>
    <p>By using SceneCraft, you agree to submit only content you own or are authorized to analyze.</p>
    <h3>Disclaimer</h3>
    <p>SceneCraft analyzes scenes using cinematic principles. You remain responsible for submitted content.</p>
    <h3>Usage Policy</h3>
    <ul>
      <li>Submit only your original scenes or excerpts you’re authorized to use.</li>
      <li>Do not submit random text or prompts.</li>
      <li>Analysis is creative insight, not legal advice.</li>
    </ul>
    <h3>Copyright Responsibility</h3>
    <p>You are fully responsible for the originality and rights of submitted content. SceneCraft does not store your scenes.</p>
    <hr>
    <p>© SceneCraft 2025. All rights reserved.</p>
  </body>
</html>
"""
    return HTMLResponse(content=html)

@app.get("/")
def root():
    return {"message": "SceneCraft backend is live."}
