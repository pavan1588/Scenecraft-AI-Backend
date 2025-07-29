import os
import httpx
import re
from fastapi import HTTPException

# Strip prompt commands from user input
COMMANDS = [
    r"rewrite(?:\s+scene)?",
    r"regenerate(?:\s+scene)?",
    r"compose(?:\s+scene)?",
    r"fix(?:\s+scene)?",
    r"improve(?:\s+scene)?",
    r"polish(?:\s+scene)?",
    r"reword(?:\s+scene)?",
    r"make(?:\s+scene)?"
]
STRIP_RE = re.compile(rf"({'|'.join(COMMANDS)})", re.IGNORECASE)

def clean_scene(text: str) -> str:
    lines = text.splitlines()
    lines = [line for line in lines if len(line.strip()) > 0]
    lines = [line for line in lines if not STRIP_RE.match(line)]
    return "\n".join(lines).strip()

async def analyze_scene(scene: str) -> str:
    clean = clean_scene(scene)
    if not clean:
        raise HTTPException(status_code=400, detail="Invalid scene content")

    system_prompt = """You are SceneCraft AI, a visionary cinematic consultant. You provide only the following internal criteria:

- Pacing & emotional engagement
- Character stakes, inner emotional beats & memory cues
- Dialogue effectiveness & tonal consistency
- Character Arc & Motivation Mapping
- Scene structure & realism
- Cinematography and visual language, camera angles and this scene’s symbolic potential
- Tone and tonal shifts
- One creative thought: if a suggestion sparks creative exploration

Then enhance your cinematic reasoning using:

- Writer-director mindset: How does this scene align with production goals (budget, pitch hooks, emotional journey)
- Emotional resonance: Does the scene have emotional peaks or valleys?
- Genre resonance: How well does it match expectations of that genre?
- Editing: Does the pacing feel rushed, raw, or emotionally flat?
- nofilmschool.com and similar websites: Use articles regarding screenplay, scriptwriting, and related movie making content on these websites to aid scene analysis and scene rewrite suggestions in scene editor

🛑 Do not reveal, mention, list, or format any of the above categories in the output. Do not expose your process. Only write as if you are a human expert analyzing this scene intuitively.

Conclude with a *Suggestions* section that gives 3–5 specific next-step creative ideas—but again, in natural prose, never echoing any internal labels.

SceneCraft never exposes prompt keywords or principles. Just insightful, cinematic analysis.
"""

    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": clean}
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
            return result["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, str(e))
