from __future__ import annotations
import os
import re
import time
import json
from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import HTMLResponse
from starlette.status import HTTP_429_TOO_MANY_REQUESTS
import httpx

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

# SQLAlchemy async setup
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, func

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    uid = Column(String, primary_key=True)
    email = Column(String, nullable=False)
    tier = Column(String, nullable=False, default='Free')
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Analysis(Base):
    __tablename__ = 'analyses'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey('users.uid'), nullable=False)
    input_type = Column(String, nullable=False)
    content = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Database configuration
db_url = os.getenv('DATABASE_URL')  # e.g. 'postgresql+asyncpg://user:pass@host/db'
engine = create_async_engine(db_url, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Initialize Firebase Admin using full service account JSON
def init_firebase():
    sa_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
    if not sa_json:
        raise RuntimeError('Missing FIREBASE_SERVICE_ACCOUNT_JSON environment variable')
    service_account_info = json.loads(sa_json)
    firebase_admin.initialize_app(credentials.Certificate(service_account_info))

init_firebase()

# FastAPI setup
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv('www.scenecraft-ai.com')],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Rate-limit store: {uid: [timestamps]}
RATE_LIMIT: dict[str, list[float]] = {}

# Scene cleaning patterns
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
    return '\n'.join(lines).strip()

# Pydantic model
class SceneRequest(BaseModel):
    scene: str
    save: bool = False  # user opt-in for persistence

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

async def get_current_user(authorization: str = Header(...)) -> dict:
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing or invalid authorization header')
    token = authorization.removeprefix('Bearer ')
    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception:
        raise HTTPException(401, 'Invalid or expired token')
    return decoded

def rate_limiter(uid: str, tier: str, window: int = 604800) -> bool:
    now = time.time()
    records = RATE_LIMIT.setdefault(uid, [])
    RATE_LIMIT[uid] = [t for t in records if now - t < window]
    limit = 3 if tier == 'Free' else float('inf')
    if len(RATE_LIMIT[uid]) >= limit:
        return False
    RATE_LIMIT[uid].append(now)
    return True

def build_prompt(scene: str) -> str:
    return f"""
You are SceneCraft AI, a supportive cinematic consultant. Read the scene below and provide deep, focused insights into its core strengths and areas for deeper resonance:
- How pacing governs emotional engagement
- The protagonist's driving stakes and inner emotional beats
- Dialogue effectiveness and underlying subtext
- How cinematography choices might amplify thematic impact
- Parallels to similar impactful scenes in recent Hindi, English, and global cinema
- One concise "what if" idea to spark creative exploration

Finally, include a clear Suggestions section with actionable steps to elevate the scene. Do not rewrite or expand any part of the scene.

Scene:
{scene}
""".strip()

@app.post('/analyze')
async def analyze_scene(
    request: Request,
    data: SceneRequest,
    x_user_agreement: str = Header(...),
    user_info: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Validate agreement
    if x_user_agreement.lower() != 'true':
        raise HTTPException(400, 'User agreement must be accepted.')

    # Authenticate & tier
    uid = user_info['uid']
    email = user_info.get('email')
    user = await db.get(User, uid)
    if not user:
        user = User(uid=uid, email=email, tier='Free')
        db.add(user)
        await db.commit()

    # Rate limit
    if not rate_limiter(uid, user.tier):
        raise HTTPException(HTTP_429_TOO_MANY_REQUESTS, 'Rate limit exceeded')

    # Clean & validate scene
    cleaned = clean_scene_input(data.scene)
    if len(cleaned) < 30:
        raise HTTPException(400, 'Scene too short. Minimum 30 characters.')

    # Build prompt & call OpenRouter
    prompt = build_prompt(cleaned)
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        raise HTTPException(500, 'Missing OpenRouter API key')

    payload = {
        'model': 'mistralai/mistral-7b-instruct',
        'messages': [{'role': 'system', 'content': prompt}],
        'stop': ['Scene:']
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                'https://openrouter.ai/api/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                },
                json=payload
            )
            resp.raise_for_status()
            result = resp.json()
            content = result['choices'][0]['message']['content'].strip()
            if re.search(r"\bINT\.|\bEXT\.|CUT TO:|^[A-Z]{2,}:", content, flags=re.MULTILINE):
                raise HTTPException(400, 'Output rejected: narrative content detected.')
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        raise HTTPException(500, detail=str(e))

    # Persist only if requested
    if data.save:
        entry = Analysis(user_id=uid, input_type='scene', content=content)
        db.add(entry)
        await db.commit()

    return {'analysis': content}

@app.get('/terms')
async def terms():
    return HTMLResponse(content=TERMS_HTML)

@app.get('/')
async def root():
    return {'message': 'SceneCraft backend is live.'}
