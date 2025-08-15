import os
import re
import json as _json
import httpx
import hashlib
from urllib.parse import quote
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

INTENT_LINE_RE = re.compile(rf"^\s*(?:please\s+)?(?:the\s+)?(?:{'|'.join(COMMANDS)})\s*$", re.IGNORECASE)
INTENT_INLINE_CMD_RE = re.compile(r"\b(?:rewrite|regenerate|compose|fix|improve|polish|reword|make)\s+(?:this|the)?\s*(?:scene|script)\b", re.IGNORECASE)
STRIP_RE = INTENT_LINE_RE
INTENT_ANYWHERE_RE = INTENT_INLINE_CMD_RE

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
    cleaned = []
    for line in text.split("\n"):
        if not line:
            continue
        if INTENT_LINE_RE.match(line):
            continue
        line = INTENT_INLINE_CMD_RE.sub("", line).strip(" :-\t")
        if line:
            cleaned.append(line)
    return "\n".join(cleaned).strip()

def _fallback_payload_from_text(text: str) -> dict:
    return {
        "summary": "Analysis",
        "analytics": {"mood": 60, "pacing": "Balanced", "realism": 70, "stakes": "Medium", "dialogue_naturalism": "Mixed", "cinematic_readiness": "Draft"},
        "beats": [],
        "suggestions": [{"title": "General Feedback", "rationale": "See text", "director_note": "", "rewrite_example": ""}],
        "comparison": "",
        "theme": {"color": "#b3d9ff", "audio": "", "mood_words": []},
        "emotional_map": {"curve_label": "Balanced", "clarity": "Moderate", "empathy": "Neutral POV"},
        "sensory": {"visual": "Medium", "auditory": "Low", "tactile": "Low", "olfactory": "Low", "gustatory": "Low", "spatial": "Medium"},
        "props": [],
        "dual_lens": {"first_timer": "—", "rewatcher": "—"},
        "integrity_alerts": [],
        "pacing_map": [],
        "growth_suggestions": [],
        "analytics_signals": [],
        "confidence": 60,
        "confidence_reason": "Moderate clarity; limited conflicting signals.",
        "pacing_annotations": [],
        "beat_markers": [],
        "storyboard_frames": [],
        "disclaimer": ("This is a first‑pass cinematic analysis to support your craft. Your voice and choices always come first."),
        "raw": (text or "").strip(),
    }

def _system_prompt() -> str:
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
    )

FREESOUND_API_KEY = os.getenv("FREESOUND_API_KEY")

async def get_freesound_url(query: str) -> str:
    if not FREESOUND_API_KEY or not query:
        return ""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://freesound.org/apiv2/search/text/",
                params={"query": query, "filter": "duration:[5 TO 60]", "sort": "score", "fields": "id,previews"},
                headers={"Authorization": f"Token {FREESOUND_API_KEY}"},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("results"):
                return data["results"][0]["previews"].get("preview-hq-mp3", "") or data["results"][0]["previews"].get("preview-lq-mp3", "")
    except Exception as e:
        print(f"[Freesound] Error: {e}")
    return ""

# ---------------- Storyboard (inline SVG with simple pictograms) -------------------
def _mood_color(mood_words):
    palette = ["#dbeafe", "#e9d5ff", "#fee2e2", "#dcfce7", "#ffedd5", "#fde68a", "#e5e7eb"]
    seed_src = (",".join(mood_words) if mood_words else "cinematic")[:64]
    idx = int(hashlib.sha256(seed_src.encode("utf-8")).hexdigest(), 16) % len(palette)
    return palette[idx]

def _wrap_lines(text: str, max_len: int = 38):
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) > max_len:
            if cur: lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur: lines.append(cur)
    return lines[:3]

def _infer_layout(caption: str):
    t = caption.lower()
    # shot size
    if any(k in t for k in ["close-up", "close up", "closeup", "cu"]): size = "cu"
    elif any(k in t for k in ["medium", "mid-shot", "mid shot", "ms"]): size = "ms"
    else: size = "ws"  # default wide

    # subject position
    if "left" in t: pos = 0.25
    elif "right" in t: pos = 0.75
    else: pos = 0.5

    # horizon hint
    if any(k in t for k in ["low angle", "looks up", "towering"]): horizon = 0.65
    elif any(k in t for k in ["high angle", "overhead", "looks down"]): horizon = 0.35
    else: horizon = 0.5

    # subject type (icon)
    subj = "person" if any(k in t for k in ["man","woman","figure","person","kid","child","driver","nikhil","elena","isabel","marcus"]) else \
           "car" if "car" in t else \
           "door" if "door" in t or "exit" in t else \
           "glass" if "glass" in t or "cup" in t or "wine" in t else "shape"

    return size, pos, horizon, subj

def _draw_subject(subj, size, pos, w, h):
    cx = int(w * pos)
    baseline = int(h*0.72)
    elems = []
    if subj == "person":
        # simple head + torso; scale by size
        scale = 1.0 if size=="ws" else (1.4 if size=="ms" else 2.0)
        r = int(10*scale)
        torso_w = int(26*scale); torso_h = int(34*scale)
        head_y = baseline - torso_h - r*2
        elems.append(f'<circle cx="{cx}" cy="{head_y+r}" r="{r}" fill="#0b2a55" opacity="0.85"/>')
        elems.append(f'<rect x="{cx-torso_w//2}" y="{baseline-torso_h}" width="{torso_w}" height="{torso_h}" rx="4" fill="#0b2a55" opacity="0.75"/>')
    elif subj == "car":
        elems.append(f'<rect x="{cx-38}" y="{baseline-18}" width="76" height="22" rx="4" fill="#0b2a55" opacity="0.75"/>')
        elems.append(f'<circle cx="{cx-24}" cy="{baseline+4}" r="6" fill="#0b2a55" opacity="0.85"/>')
        elems.append(f'<circle cx="{cx+24}" cy="{baseline+4}" r="6" fill="#0b2a55" opacity="0.85"/>')
    elif subj == "door":
        elems.append(f'<rect x="{cx-20}" y="{baseline-60}" width="40" height="60" fill="#0b2a55" opacity="0.2" stroke="#0b2a55" stroke-width="2"/>')
        elems.append(f'<circle cx="{cx+12}" cy="{baseline-32}" r="2.5" fill="#0b2a55"/>')
    elif subj == "glass":
        elems.append(f'<rect x="{cx-8}" y="{baseline-28}" width="16" height="24" rx="2" fill="#0b2a55" opacity="0.7"/>')
        elems.append(f'<rect x="{cx-12}" y="{baseline-32}" width="24" height="4" rx="2" fill="#0b2a55" opacity="0.4"/>')
    else:
        elems.append(f'<rect x="{cx-18}" y="{baseline-24}" width="36" height="28" rx="4" fill="#0b2a55" opacity="0.5"/>')
    return "\n".join(elems)

def _svg_storyboard_strings(caption: str, mood_words):
    bg = _mood_color(mood_words)
    lines = _wrap_lines(caption, 46)
    size, pos, horizon, subj = _infer_layout(caption)

    w, h = 960, 540
    thirds_x = [w/3, 2*w/3]
    thirds_y = [h/3, 2*h/3]
    horizon_y = int(h * horizon)

    # subtle vignette + stronger frame + thirds grid
    grid = (
        f'<line x1="{thirds_x[0]}" y1="0" x2="{thirds_x[0]}" y2="{h}" stroke="#8fb3ff" stroke-width="1" opacity="0.35"/>'
        f'<line x1="{thirds_x[1]}" y1="0" x2="{thirds_x[1]}" y2="{h}" stroke="#8fb3ff" stroke-width="1" opacity="0.35"/>'
        f'<line x1="0" y1="{thirds_y[0]}" x2="{w}" y2="{thirds_y[0]}" stroke="#8fb3ff" stroke-width="1" opacity="0.35"/>'
        f'<line x1="0" y1="{thirds_y[1]}" x2="{w}" y2="{thirds_y[1]}" stroke="#8fb3ff" stroke-width="1" opacity="0.35"/>'
        f'<line x1="0" y1="{horizon_y}" x2="{w}" y2="{horizon_y}" stroke="#0b2a55" stroke-width="2" opacity="0.25"/>'
    )

    subject = _draw_subject(subj, size, pos, w, h)

    svg_markup = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{bg}"/>
      <stop offset="100%" stop-color="#ffffff"/>
    </linearGradient>
    <radialGradient id="v" cx="50%" cy="50%" r="70%">
      <stop offset="60%" stop-color="rgba(0,0,0,0)"/>
      <stop offset="100%" stop-color="rgba(0,0,0,0.12)"/>
    </radialGradient>
  </defs>
  <rect x="0" y="0" width="{w}" height="{h}" fill="url(#g)"/>
  <rect x="8" y="8" width="{w-16}" height="{h-16}" fill="none" stroke="#7aa6ff" stroke-width="3" rx="12"/>
  <rect x="0" y="0" width="{w}" height="{h}" fill="url(#v)"/>
  <g>{grid}</g>
  <g>{subject}</g>
  <g font-family="ui-sans-serif,system-ui,Segoe UI,Roboto" fill="#0b2a55">
    <text x="24" y="40" font-size="26" font-weight="700">Storyboard</text>
    <text x="24" y="80" font-size="22">{(lines[0] if len(lines)>0 else "")}</text>
    <text x="24" y="110" font-size="22">{(lines[1] if len(lines)>1 else "")}</text>
    <text x="24" y="140" font-size="22">{(lines[2] if len(lines)>2 else "")}</text>
  </g>
</svg>'''
    data_url = "data:image/svg+xml;utf8," + quote(svg_markup, safe=":/,%#[]@!$&'()*+;=")
    return data_url, svg_markup

def _ensure_storyboard_images(obj: dict) -> dict:
    try:
        frames = obj.get("storyboard_frames")
        theme = obj.get("theme") or {}
        mood_words = theme.get("mood_words") or []
        if not isinstance(frames, list) or not frames:
            frames = []
            beats = obj.get("beats") or []
            order = ["Setup", "Trigger", "Escalation", "Climax", "Exit"]
            beats = sorted(beats, key=lambda b: order.index(b.get("title", "")) if (b.get("title","") in order) else 99)[:5]
            for b in beats:
                cap = (b or {}).get("insight") or (b or {}).get("title") or "Key moment"
                frames.append({"caption": str(cap).strip()[:220], "image_url": ""})
        out = []
        for f in frames[:5]:
            cap = str((f or {}).get("caption") or "Key moment")
            data_url, svg_markup = _svg_storyboard_strings(cap, mood_words)
            url = (f or {}).get("image_url") or data_url
            out.append({"caption": cap, "image_url": url, "svg": svg_markup})
        obj["storyboard_frames"] = out
    except Exception as e:
        print(f"[Storyboard] Non-fatal: {e}")
    return obj

def _prune_output(obj: dict) -> dict:
    try:
        if isinstance(obj.get("beats"), list): obj["beats"] = obj["beats"][:5]
        if isinstance(obj.get("suggestions"), list): obj["suggestions"] = obj["suggestions"][:5]
        if isinstance(obj.get("props"), list): obj["props"] = obj["props"][:5]
        if isinstance(obj.get("integrity_alerts"), list): obj["integrity_alerts"] = obj["integrity_alerts"][:5]
        if isinstance(obj.get("growth_suggestions"), list): obj["growth_suggestions"] = obj["growth_suggestions"][:3]
        if isinstance(obj.get("analytics_signals"), list): obj["analytics_signals"] = obj["analytics_signals"][:5]
        if isinstance(obj.get("pacing_annotations"), list): obj["pacing_annotations"] = obj["pacing_annotations"][:8]
        if isinstance(obj.get("beat_markers"), list): obj["beat_markers"] = obj["beat_markers"][:5]
        if isinstance(obj.get("storyboard_frames"), list): obj["storyboard_frames"] = obj["storyboard_frames"][:5]
        pm = obj.get("pacing_map")
        if isinstance(pm, list) and len(pm) > 40:
            stride = max(1, len(pm) // 40)
            obj["pacing_map"] = pm[::stride][:40]
    except Exception:
        pass
    return obj

def _clamp_0_100_list(arr):
    if not isinstance(arr, list): return []
    out = []
    for v in arr:
        try: f = float(v)
        except Exception: f = 0.0
        f = 0 if f < 0 else (100 if f > 100 else f)
        out.append(int(round(f)))
    return out

async def analyze_scene(scene: str) -> dict:
    raw = scene or ""
    clean = clean_scene(raw)

    if INTENT_LINE_RE.match(raw.strip()):
        raise HTTPException(status_code=400, detail="SceneCraft does not generate scenes. Please submit your own scene or script for analysis.")
    if INTENT_INLINE_CMD_RE.search(raw):
        raise HTTPException(status_code=400, detail="SceneCraft does not generate scenes. Please submit your own scene or script for analysis.")
    if not clean:
        raise HTTPException(status_code=400, detail="Invalid scene content")

    wc = len(re.findall(r"\b\w+\b", clean))
    if wc < MIN_WORDS:
        raise HTTPException(status_code=400, detail="Scene must be at least one page (~250 words) for cinematic analysis.")
    if wc > MAX_WORDS:
        raise HTTPException(status_code=400, detail=f"Scene is too long for a single-pass analysis (> {MAX_WORDS} words). Consider splitting it.")

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing OPENROUTER_API_KEY.")

    base_payload = {
        "model": os.getenv("OPENROUTER_MODEL", "gpt-4o"),
        "temperature": 0.5,
        "messages": [{"role": "system", "content": _system_prompt()}, {"role": "user", "content": clean}],
    }

    async def _post(payload):
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            r = await client.post("https://openrouter.ai/api/v1/chat/completions",
                                  headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                                  json=payload)
            r.raise_for_status()
            return r.json()

    try:
        json_mode_payload = dict(base_payload); json_mode_payload["response_format"] = {"type": "json_object"}
        try:
            data = await _post(json_mode_payload)
        except httpx.HTTPStatusError as e:
            txt = ""
            try: txt = e.response.text or ""
            except Exception: pass
            if e.response.status_code in (400,404,422) or "response_format" in txt.lower():
                data = await _post(base_payload)
            else:
                raise

        content = (data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()

        try:
            obj = _json.loads(content)
        except Exception:
            trimmed = content.strip()
            if trimmed.startswith("```"):
                trimmed = trimmed.strip("`")
                if trimmed[:4].lower() == "json":
                    trimmed = trimmed[4:]
            try:
                obj = _json.loads(trimmed)
            except Exception:
                return _fallback_payload_from_text(content)

        # Defaults
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
        obj.setdefault("emotional_map", {"curve_label": "Balanced", "clarity": "Moderate", "empathy": "Neutral POV"})
        obj.setdefault("sensory", {"visual": "Medium", "auditory": "Low", "tactile": "Low", "olfactory": "Low", "gustatory": "Low", "spatial": "Medium"})
        obj.setdefault("props", [])
        obj.setdefault("dual_lens", {"first_timer": "", "rewatcher": ""})
        obj.setdefault("integrity_alerts", [])
        obj.setdefault("pacing_map", [])
        obj.setdefault("growth_suggestions", [])
        obj.setdefault("analytics_signals", [])
        obj.setdefault("confidence", 60)
        obj.setdefault("confidence_reason", "Moderate clarity; limited conflicting signals.")
        obj.setdefault("pacing_annotations", [])
        obj.setdefault("beat_markers", [])
        obj.setdefault("storyboard_frames", [])
        obj.setdefault("disclaimer", "This is a first‑pass cinematic analysis to support your craft. Your voice and choices always come first.")

        if isinstance(obj.get("pacing_map"), list):
            obj["pacing_map"] = _clamp_0_100_list(obj["pacing_map"])

        # ambience (best effort)
        try:
            theme = obj.get("theme", {}) or {}
            mood_words = theme.get("mood_words") or []
            if isinstance(mood_words, list) and mood_words:
                fs = await get_freesound_url(str(mood_words[0]).strip())
                if fs:
                    theme["audio_url"] = fs
                    obj["theme"] = theme
        except Exception as _e:
            print(f"[Freesound] Non-fatal: {_e}")

        # STORYBOARD (inline SVG + data URL fallback)
        obj = _ensure_storyboard_images(obj)

        # prune
        obj = _prune_output(obj)
        return obj

    except httpx.HTTPStatusError as e:
        try:
            err_json = e.response.json()
            detail = (err_json.get("error") or {}).get("message") or e.response.text
        except Exception:
            detail = e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
