import os
import re
import json as _json
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
    r"make(?:\s+scene)?",
]

# Full-line intent (exact command lines only)
INTENT_LINE_RE = re.compile(
    rf"^\s*(?:please\s+)?(?:the\s+)?(?:{'|'.join(COMMANDS)})\s*$",
    re.IGNORECASE,
)

# Inline — ONLY when clearly instructing to modify/generate a scene/script
INTENT_INLINE_CMD_RE = re.compile(
    r"\b(?:rewrite|regenerate|compose|fix|improve|polish|reword|make)\s+(?:this|the)?\s*(?:scene|script)\b",
    re.IGNORECASE,
)

# --- Backward compatibility for backend imports ---
STRIP_RE = INTENT_LINE_RE
INTENT_ANYWHERE_RE = INTENT_INLINE_CMD_RE  # alias for legacy import paths

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
        # Remove full-line commands entirely
        if INTENT_LINE_RE.match(line):
            continue
        # Remove only explicit inline "modify this scene/script" commands
        line = INTENT_INLINE_CMD_RE.sub("", line).strip(" :-\t")
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()

def _fallback_payload_from_text(text: str) -> dict:
    """
    If the model doesn't return valid JSON (rare), wrap the text so frontend
    still renders something coherent. Includes safe defaults for new UI keys.
    """
    return {
        "summary": "Analysis",
        "analytics": {
            "mood": 60,
            "pacing": "Balanced",
            "realism": 70,
            "stakes": "Medium",
            "dialogue_naturalism": "Mixed",
            "cinematic_readiness": "Draft",
        },
        "beats": [],
        "suggestions": [
            {
                "title": "General Feedback",
                "rationale": "See text",
                "director_note": "",
                "rewrite_example": "",
            },
        ],
        "comparison": "",
        "theme": {"color": "#b3d9ff", "audio": "", "mood_words": []},
        # New layers (safe defaults)
        "emotional_map": {
            "curve_label": "Balanced",
            "clarity": "Moderate",
            "empathy": "Neutral POV",
        },
        "sensory": {
            "visual": "Medium",
            "auditory": "Low",
            "tactile": "Low",
            "olfactory": "Low",
            "gustatory": "Low",
            "spatial": "Medium",
        },
        "props": [],
        "dual_lens": {"first_timer": "—", "rewatcher": "—"},
        "integrity_alerts": [],
        "pacing_map": [],
        "growth_suggestions": [],
        # Evidence/markers (already supported)
        "analytics_signals": [],
        "confidence": 60,
        "confidence_reason": "Moderate clarity; limited conflicting signals.",
        "pacing_annotations": [],
        "beat_markers": [],
        # Storyboard (NEW)
        "storyboard_frames": [],  # [{"image_url": "...", "caption": "..."}]
        "disclaimer": (
            "This is a first‑pass cinematic analysis to support your craft. "
            "Your voice and choices always come first."
        ),
        "raw": (text or "").strip(),
    }

def _system_prompt() -> str:
    # === Benchmarks & Rival Layers preserved verbatim, plus added silent lenses ===
    return (
        "You are CineOracle — a layered cinematic intelligence. You perform all of SceneCraft AI’s existing "
        "scene analysis while silently running advanced internal passes. Never reveal internal steps.\n\n"

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

        "ADDITIONAL SILENT LENSES (apply but do not list):\n"
        "- Director-level: Spatial Grammar; Temporal Pressure; Energy Transitions; Camera Mind; Contrast Layer.\n"
        "- Writer/script-doctor: Subtext Richness; Narrative Gravity; Dialogue Dynamics Map; Hook & Release; Character Echoes.\n"
        "- Audience-centric: Emotional Stickiness; Social Share Potential; Cultural Mirror; Genre Pulse Match; Multi‑Audience Readability.\n"
        "- Deep craft: Sensory Weave; Symbol/Object Resonance; Tone vs Story DNA; Emotional Foreshadowing; Rhythmic Breath Check.\n"
        "- SceneCraft‑exclusive: Silent Scene Reimagination.\n\n"

        "OUTPUT CONTRACT — Return STRICT JSON ONLY (no markdown/code fences) with this schema:\n"
        "{\n"
        '  "summary": string,\n'
        '  "analytics": {\n'
        '    "mood": integer (0-100),\n'
        '    "pacing": "Tight" | "Balanced" | "Meandering",\n'
        '    "realism": integer (0-100),\n'
        '    "stakes": "Low" | "Medium" | "High",\n'
        '    "dialogue_naturalism": "Weak" | "Mixed" | "Strong",\n'
        '    "cinematic_readiness": "Draft" | "Shootable" | "Strong"\n'
        "  },\n"
        '  "analytics_signals": [\n'
        '    {"claim": string, "evidence": "short quote or detail (≤12 words)"}\n'
        "  ],\n"
        '  "confidence": integer (0-100),\n'
        '  "confidence_reason": string,\n'
        '  "beats": [\n'
        '    {"title": "Setup" | "Trigger" | "Escalation" | "Climax" | "Exit", "insight": string}\n'
        "  ],\n"
        '  "suggestions": [\n'
        '    {"title": string, "rationale": string, "director_note": string, "rewrite_example": string}\n'
        "  ],\n"
        '  "comparison": string,\n'
        '  "theme": {"color": "#b3d9ff", "audio": string, "mood_words": [string, ...]},\n'
        '  "emotional_map": {"curve_label": string, "clarity": "Low"|"Moderate"|"High", "empathy": string},\n'
        '  "sensory": {"visual":string,"auditory":string,"tactile":string,"olfactory":string,"gustatory":string,"spatial":string},\n'
        '  "props": [{"name":string,"significance":string}],\n'
        '  "dual_lens": {"first_timer":string,"rewatcher":string},\n'
        '  "integrity_alerts": [{"level":"info"|"warn","message":string}],\n'
        '  "pacing_map": [integer 0-100, ...],\n'
        '  "pacing_annotations": [{"i": integer, "label": "spike"|"build"|"lull"|"release", "note": string}],\n'
        '  "beat_markers": [{"i": integer, "beat": "Setup"|"Trigger"|"Escalation"|"Climax"|"Exit"}],\n'
        '  "growth_suggestions": [string | {"experiment":string,"why":string,"expected_effect":string,"risk":string}],\n'
        '  "storyboard_frames": [{"image_url": string, "caption": string}],\n'
        '  "disclaimer": string\n'
        "}\n\n"

        "CLARITY & BREVITY RULES (very important):\n"
        "- Keep the output uncluttered and human-readable.\n"
        "- summary: ~80–120 words max, flowing like a thoughtful script doctor.\n"
        "- beats: max 5, each insight ≤ 1–2 sentences.\n"
        "- suggestions: max 5; each rationale ≤ 2 sentences; director_note ≤ 1 sentence; rewrite_example ≤ 2 lines (optional).\n"
        "- props: list only the top 3–5 objects that truly matter.\n"
        "- dual_lens: 1 short line each (≤ ~25 words).\n"
        "- emotional_map fields: concise labels (3–5 words each).\n"
        "- sensory values: use Low/Medium/High (or short phrase) per channel.\n"
        "- integrity_alerts: only if needed; ≤ 5 total.\n"
        "- growth_suggestions: ≤ 3.\n"
        "- pacing_map: 20–40 points across the scene, representing micro‑tension.\n"
        "- Do NOT invent new plot content; analyze only what’s present.\n"
        "- Maintain a supportive, collaborative tone.\n"
        "\nEVIDENCE & RIGOR RULES:\n"
        "- For analytics_signals, tie claims to brief textual evidence (≤12 words).\n"
        "- Only add pacing_annotations where the shift is clear; avoid guesswork.\n"
        "- beat_markers indices should align to pacing_map length (approximate is fine).\n"
        "- Growth suggestions should be strategic (not line edits) and name why/effect/risk.\n"
        "- Storyboard frames should be 3–5 key visuals tied to beats; concise captions.\n"
    )

# ------------------------ Freesound integration (optional) -------------------------
FREESOUND_API_KEY = os.getenv("FREESOUND_API_KEY")

async def get_freesound_url(query: str) -> str:
    """
    Fetch an ambience sound URL from Freesound based on a mood query.
    Returns a direct MP3 preview URL when available, else "".
    """
    if not FREESOUND_API_KEY or not query:
        return ""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://freesound.org/apiv2/search/text/",
                params={
                    "query": query,
                    "filter": "duration:[5 TO 60]",  # short loops
                    "sort": "score",
                    "fields": "id,previews",
                },
                headers={"Authorization": f"Token {FREESOUND_API_KEY}"},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("results"):
                return data["results"][0]["previews"].get("preview-hq-mp3", "") or \
                       data["results"][0]["previews"].get("preview-lq-mp3", "")
    except Exception as e:
        # Non-fatal: just skip audio if anything goes wrong
        print(f"[Freesound] Error fetching sound: {e}")
    return ""

# -----------------------------------------------------------------------------------

def _prune_output(obj: dict) -> dict:
    """
    Light curation to keep the UI uncluttered. We don't alter meaning,
    just cap lengths so the front-end stays breathable.
    """
    try:
        # Cap arrays to readable sizes
        if isinstance(obj.get("beats"), list):
            obj["beats"] = obj["beats"][:5]
        if isinstance(obj.get("suggestions"), list):
            obj["suggestions"] = obj["suggestions"][:5]
        if isinstance(obj.get("props"), list):
            obj["props"] = obj["props"][:5]
        if isinstance(obj.get("integrity_alerts"), list):
            obj["integrity_alerts"] = obj["integrity_alerts"][:5]
        if isinstance(obj.get("growth_suggestions"), list):
            obj["growth_suggestions"] = obj["growth_suggestions"][:3]

        # Evidence/overlays clamps (already supported)
        if isinstance(obj.get("analytics_signals"), list):
            obj["analytics_signals"] = obj["analytics_signals"][:5]
        if isinstance(obj.get("pacing_annotations"), list):
            obj["pacing_annotations"] = obj["pacing_annotations"][:8]
        if isinstance(obj.get("beat_markers"), list):
            obj["beat_markers"] = obj["beat_markers"][:5]

        # Storyboard frames: keep 3–5 max
        if isinstance(obj.get("storyboard_frames"), list):
            obj["storyboard_frames"] = obj["storyboard_frames"][:5]

        # Pacing map: keep within 20–40 points if oversized
        pm = obj.get("pacing_map")
        if isinstance(pm, list) and len(pm) > 40:
            # downsample by simple stride
            stride = max(1, len(pm) // 40)
            obj["pacing_map"] = pm[::stride][:40]
    except Exception:
        # Never let pruning break output
        pass
    return obj

# --- Tiny safety clamp for chart stability (no logic changes) ---
def _clamp_0_100_list(arr):
    if not isinstance(arr, list):
        return []
    out = []
    for v in arr:
        try:
            f = float(v)
        except Exception:
            f = 0.0
        if f < 0: f = 0.0
        if f > 100: f = 100.0
        out.append(int(round(f)))
    return out

async def analyze_scene(scene: str) -> dict:
    raw = scene or ""
    clean = clean_scene(raw)

    # Guards
    if INTENT_LINE_RE.match(raw.strip()):
        raise HTTPException(
            status_code=400,
            detail="SceneCraft does not generate scenes. Please submit your own scene or script for analysis.",
        )
    if INTENT_INLINE_CMD_RE.search(raw):
        raise HTTPException(
            status_code=400,
            detail="SceneCraft does not generate scenes. Please submit your own scene or script for analysis.",
        )

    if not clean:
        raise HTTPException(status_code=400, detail="Invalid scene content")

    # word count
    word_count = len(re.findall(r"\b\w+\b", clean))
    if word_count < MIN_WORDS:
        raise HTTPException(
            status_code=400,
            detail="Scene must be at least one page (~250 words) for cinematic analysis.",
        )
    if word_count > MAX_WORDS:
        raise HTTPException(
            status_code=400,
            detail=f"Scene is too long for a single-pass analysis (> {MAX_WORDS} words). Consider splitting it.",
        )

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing OPENROUTER_API_KEY.")

    # --- call OpenRouter with JSON mode, then fallback if unsupported ---
    base_payload = {
        "model": os.getenv("OPENROUTER_MODEL", "gpt-4o"),
        "temperature": 0.5,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": clean},
        ],
    }

    async def _post(payload):
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            r.raise_for_status()
            return r.json()

    try:
        # 1) Try JSON mode
        json_mode_payload = dict(base_payload)
        json_mode_payload["response_format"] = {"type": "json_object"}
        try:
            data = await _post(json_mode_payload)
        except httpx.HTTPStatusError as e:
            # If provider/model rejects response_format, fallback without it
            detail_text = ""
            try:
                detail_text = e.response.text or ""
            except Exception:
                pass
            if e.response.status_code in (400, 404, 422) or "response_format" in detail_text.lower():
                data = await _post(base_payload)
            else:
                raise

        content = (
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
        ).strip()

        # Parse STRICT JSON if present
        try:
            obj = _json.loads(content)
        except Exception:
            # Some providers wrap JSON in fences — try to strip
            trimmed = content.strip()
            if trimmed.startswith("```"):
                trimmed = trimmed.strip("`")
                if trimmed[:4].lower() == "json":
                    trimmed = trimmed[4:]
            try:
                obj = _json.loads(trimmed)
            except Exception:
                # Final safety: wrap raw text so UI still shows something useful
                return _fallback_payload_from_text(content)

        # Minimal defaults so frontend never breaks
        obj.setdefault("summary", "Analysis")
        obj.setdefault("analytics", {})
        obj["analytics"].setdefault("mood", 60)
        obj["analytics"].setdefault("pacing", "Balanced")
        obj["analytics"].setdefault("realism", 70)
        obj["analytics"].setdefault("stakes", "Medium")
        obj["analytics"].setdefault("dialogue_naturalism", "Mixed")
        obj["analytics"].setdefault("cinematic_readiness", "Draft")
        obj.setdefault("beats", [])
        obj.setdefault("suggestions", [])
        obj.setdefault("comparison", "")
        obj.setdefault("theme", {"color": "#b3d9ff", "audio": "", "mood_words": []})
        obj.setdefault(
            "emotional_map",
            {"curve_label": "Balanced", "clarity": "Moderate", "empathy": "Neutral POV"},
        )
        obj.setdefault(
            "sensory",
            {
                "visual": "Medium",
                "auditory": "Low",
                "tactile": "Low",
                "olfactory": "Low",
                "gustatory": "Low",
                "spatial": "Medium",
            },
        )
        obj.setdefault("props", [])
        obj.setdefault("dual_lens", {"first_timer": "", "rewatcher": ""})
        obj.setdefault("integrity_alerts", [])
        obj.setdefault("pacing_map", [])
        obj.setdefault("growth_suggestions", [])
        # Evidence/overlays defaults
        obj.setdefault("analytics_signals", [])
        obj.setdefault("confidence", 60)
        obj.setdefault("confidence_reason", "Moderate clarity; limited conflicting signals.")
        obj.setdefault("pacing_annotations", [])
        obj.setdefault("beat_markers", [])
        # Storyboard defaults
        obj.setdefault("storyboard_frames", [])
        obj.setdefault(
            "disclaimer",
            "This is a first‑pass cinematic analysis to support your craft. Your voice and choices always come first.",
        )

        # Clamp pacing_map to 0..100
        if isinstance(obj.get("pacing_map"), list):
            obj["pacing_map"] = _clamp_0_100_list(obj["pacing_map"])

        # ---------------- Freesound hook (non-intrusive) ----------------
        try:
            theme = obj.get("theme", {}) or {}
            mood_words = theme.get("mood_words") or []
            mood_word = ""
            if isinstance(mood_words, list) and mood_words:
                mood_word = str(mood_words[0]).strip()

            if mood_word:
                fs_url = await get_freesound_url(mood_word)
                if fs_url:
                    theme["audio_url"] = fs_url
                    obj["theme"] = theme
        except Exception as _e:
            # Never fail analysis because audio lookup had issues
            print(f"[Freesound] Non-fatal: {_e}")
        # ----------------------------------------------------------------

        # Final pruning for an uncluttered UX
        obj = _prune_output(obj)

        return obj

    except httpx.HTTPStatusError as e:
        # Surface provider error message cleanly
        try:
            err_json = e.response.json()
            detail = (err_json.get("error") or {}).get("message") or e.response.text
        except Exception:
            detail = e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
