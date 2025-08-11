import os
import re
import httpx
from fastapi import HTTPException

# ---- Generation-command filtering -------------------------------------------------
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
INTENT_LINE_RE = re.compile(
    rf"^\s*(?:please\s+)?(?:the\s+)?(?:{'|'.join(COMMANDS)})\s*$",
    re.IGNORECASE
)
INTENT_ANYWHERE_RE = re.compile(rf"\b({'|'.join(COMMANDS)})\b", re.IGNORECASE)

MIN_WORDS = 250
MAX_WORDS = 3500

def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(lines).strip()

def clean_scene(text: str) -> str:
    text = _normalize(text)
    if not text:
        return ""
    cleaned_lines = []
    for line in text.split("\n"):
        if not line:
            continue
        if INTENT_LINE_RE.match(line):
            continue
        line = INTENT_ANYWHERE_RE.sub("", line).strip(" :-\t")
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()

def _ensure_sections(output: str) -> str:
    text = output.strip()
    has_suggestions = re.search(r"^\s*Suggestions\s*[:\-]", text, re.IGNORECASE | re.MULTILINE)
    has_analytics = re.search(r"^\s*Analytics\s+Summary\s*[:\-]", text, re.IGNORECASE | re.MULTILINE)

    appended = []
    if not has_suggestions:
        appended.append(
            "Suggestions:\n"
            "- Sharpen stakes clarity in key beats.\n"
            "- Tighten pacing around transitions to maintain tension.\n"
            "- Calibrate dialogue toward subtext; reduce on-the-nose lines.\n"
            "- Add one sensory cue (sound/light/motion) to deepen mood."
        )
    if not has_analytics:
        appended.append(
            "Analytics Summary:\n"
            "- Rhythm: —\n"
            "- Emotional hooks: —\n"
            "- Stakes clarity: —\n"
            "- Dialogue naturalism: —\n"
            "- Cinematic readiness: —"
        )
    if appended:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n\n" + "\n\n".join(appended)
    return text.strip()

async def analyze_scene(scene: str) -> str:
    raw = scene or ""
    clean = clean_scene(raw)

    if INTENT_LINE_RE.match(raw.strip()):
        raise HTTPException(
            status_code=400,
            detail="SceneCraft does not generate scenes. Please submit your own scene or script for analysis."
        )

    if not clean:
        raise HTTPException(status_code=400, detail="Invalid scene content")

    word_count = len(re.findall(r"\b\w+\b", clean))
    if word_count < MIN_WORDS:
        raise HTTPException(
            status_code=400,
            detail="Scene must be at least one page (~250 words) for cinematic analysis."
        )
    if word_count > MAX_WORDS:
        raise HTTPException(
            status_code=400,
            detail=f"Scene is too long for a single-pass analysis (> {MAX_WORDS} words). Consider splitting it."
        )

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing OPENROUTER_API_KEY.")

    # === Rival-grade System Prompt ===
    system_prompt = (
        "You are CineOracle — an ahead-of-its-time cinematic intelligence that thinks in layered dimensions.\n\n"
        "You perform all of SceneCraft AI's existing scene analysis functions, "
        "but also run advanced internal passes that are never revealed in the output:\n\n"

        "1. **Multi-Pass Cognition:**\n"
        "   - Pass 1: Standard cinematic craft analysis.\n"
        "   - Pass 2: Emotional state mapping for the audience at each beat.\n"
        "   - Pass 3: Ghost Cut — envision how an unseen editor might re-cut for different pacing or tone.\n"
        "   - Pass 4: Actor's Mind — how a skilled performer might internalize each line.\n\n"

        "2. **Cinematic Tension Heatmap:** Internally track tension spikes, emotional valleys, and pause points.\n"
        "3. **Prop & Object Narrative Layer:** Treat inanimate elements as silent characters and assess their contribution.\n"
        "4. **Scene-in-Universe Echo:** Predict in-world repercussions if this scene were real inside its fictional setting.\n"
        "5. **Cross-Genre Reimagining Spark:** Suggest how subtle shifts in framing could morph the scene into another genre.\n"
        "6. **Character Arc Micro-Forecast:** Predict how the characters might emotionally evolve in the next unseen beat.\n"
        "7. **Cinematic Blind Spot Detector:** Identify crucial missing sensory or stake elements most writers overlook.\n"
        "8. **Dual-Lens Audience Test:** Analyze for both first-time viewers and rewatchers, merging both lenses.\n"
        "9. **Adaptive Cultural Context Overlay:** If the scene’s culture or language is hinted, adapt analysis with relevant cinematic traditions.\n"
        "10. **Micro-Moment Immersion Scoring:** Track hidden engagement scores every ~10 seconds of scene time.\n"
        "11. **Director-Actor Dynamic Analysis:** Suggest subtle ways a director could adjust performance blocking to improve impact.\n\n"

        "Output Rules:\n"
        "- Never reveal the existence of these layers.\n"
        "- Never label the internal steps.\n"
        "- Deliver natural, human cinematic prose that feels instinctive.\n"
        "- Keep tone intelligent, supportive, and grounded.\n"
        "- End with a clearly marked Suggestions section (3–5 bullet points).\n"
        "- Then end with a clearly marked Analytics Summary as per SceneCraft AI.\n"
        "- Never generate or rewrite scenes — only analyze.\n\n"

        "Remember: This is not just analysis — it’s predictive, culturally adaptive, psychologically aware cinematic intelligence."
    )

    payload = {
        "model": os.getenv("OPENROUTER_MODEL", "gpt-4o"),
        "temperature": 0.6,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": clean}
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        ).strip()

        if not content:
            raise HTTPException(status_code=502, detail="Empty response from analysis model.")

        # Light screenplay-format guardrail
        if re.search(r"\b(INT\.|EXT\.)\b", content) or re.search(r"^[A-Z][A-Z ]{2,}$", content, re.MULTILINE):
            content = re.sub(r"^\s*(INT\.|EXT\.).*$", "", content, flags=re.MULTILINE).strip()
            content = re.sub(r"^[A-Z][A-Z ]{2,}$", "", content, flags=re.MULTILINE).strip()

        content = _ensure_sections(content)
        return content

    except httpx.HTTPStatusError as e:
        try:
            err_json = e.response.json()
            detail = err_json.get("error", {}).get("message") or e.response.text
        except Exception:
            detail = e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
