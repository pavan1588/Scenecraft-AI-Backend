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
# Full-line intent
INTENT_LINE_RE = re.compile(
    rf"^\s*(?:please\s+)?(?:the\s+)?(?:{'|'.join(COMMANDS)})\s*$",
    re.IGNORECASE
)
# Anywhere in a line
INTENT_ANYWHERE_RE = re.compile(rf"\b({'|'.join(COMMANDS)})\b", re.IGNORECASE)

# --- Backward compatibility for backend imports ---
STRIP_RE = INTENT_LINE_RE

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

    # === Merged System Prompt: Original 8 Benchmarks + 11 Rival Layers ===
    system_prompt = (
        "You are CineOracle — a layered cinematic intelligence. You perform all of SceneCraft AI’s existing"
        " scene analysis while silently running advanced internal passes. Never reveal internal steps.\n\n"

        "CINEMATIC BENCHMARKS (apply internally; do NOT list or label in output):\n"
        "1) Scene Structure & Beats — setup, trigger, escalation/tension, climax, resolution.\n"
        "2) Scene Grammar — flow of action/dialogue/description; economy; visual clarity.\n"
        "3) Realism & Authenticity — believability; emotional truth; behavioral plausibility.\n"
        "4) Cinematic Language — camera/shot composition, sound, lighting, symbols, motifs.\n"
        "5) Pacing & Rhythm — internal tempo; action/dialogue balance; micro-tension beats.\n"
        "6) Character Stakes & Motivation — emotional drive; psychological presence; unity of opposites.\n"
        "7) Editing & Transitions — connective tissue, contrasts, thematic continuity.\n"
        "8) Audience Resonance — how it lands given current genre expectations.\n\n"

        "RIVAL-GRADE LAYERS (silent, never exposed):\n"
        "1) Multi-Pass Cognition: craft → audience emotional map → Ghost Cut (editorial) → Actor’s Mind.\n"
        "2) Cinematic Tension Heatmap: track spikes, valleys, pause points.\n"
        "3) Prop & Object Narrative Layer: treat inanimate elements as silent characters.\n"
        "4) Scene-in-Universe Echo: infer in-world repercussions.\n"
        "5) Cross-Genre Reimagining Spark: tiny reframing hints across genres.\n"
        "6) Character Arc Micro-Forecast: predict next unseen beat to test propulsion.\n"
        "7) Blind Spot Detector: surface missing sensory ground, stakes, or spatial clarity.\n"
        "8) Dual-Lens Audience Test: first-timer vs rewatcher synthesis.\n"
        "9) Adaptive Cultural Overlay: respect local idiom/tradition when hinted.\n"
        "10) Micro-Moment Immersion Scoring: hidden engagement every ~10s of scene time.\n"
        "11) Director-Actor Dynamic Analysis: subtle blocking/performance adjustments.\n\n"

        "OUTPUT RULES:\n"
        "- Write natural, human, grounded cinematic prose (no lists except in the final Suggestions and Analytics sections).\n"
        "- Keep tone intelligent, supportive, and specific to the page; never generate or extend scenes.\n"
        "- End with a clearly marked Suggestions section (3–5 concise bullets).\n"
        "- Then end with a clearly marked Analytics Summary capturing rhythm, hooks, stakes clarity, dialogue naturalism, and cinematic readiness.\n"
        "- Never name or expose benchmarks or internal layers.\n"
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

        # Guardrails: never allow screenplay output
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
