import os
import re
import json as _json
import hashlib
import base64
from urllib.parse import quote
# ---- soft-import httpx (recent fix) --------------------------------------------
try:
    import httpx
except Exception:
    httpx = None
# --------------------------------------------------------------------------------
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
# e.g., "please improve this scene", "rewrite the script"
INTENT_INLINE_CMD_RE = re.compile(
    r"\b(?:rewrite|regenerate|compose|fix|improve|polish|reword|make)\s+(?:this|the)?\s*(?:scene|script)\b",
    re.IGNORECASE,
)

# --- Backward compatibility for backend imports ---
STRIP_RE = INTENT_LINE_RE
INTENT_ANYWHERE_RE = INTENT_INLINE_CMD_RE  # alias for legacy import paths

MIN_WORDS = 250
MAX_WORDS = 3500

# ---------------- Optional storyboard image generation (server-side) ---------------
STORYBOARD_ENABLE = os.getenv("SC_STORYBOARD_ENABLE", "false").lower() in {"1", "true", "yes"}
STORYBOARD_PROVIDER = os.getenv("SC_STORYBOARD_PROVIDER", "openai")  # "openai" | "stability" | "off"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY", "").strip()
STORYBOARD_MAX_FRAMES = int(os.getenv("SC_STORYBOARD_MAX_FRAMES", "4"))

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
        "analytics_signals": [],
        "confidence": 60,
        "confidence_reason": "Moderate clarity; limited conflicting signals.",
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
        "pacing_annotations": [],
        "beat_markers": [],
        "growth_suggestions": [],
        "disclaimer": (
            "This is a first‑pass cinematic analysis to support your craft. "
            "Your voice and choices always come first."
        ),
        "storyboard_frames": [],
        "raw": (text or "").strip(),
    }

def _system_prompt() -> str:
    # >>> Your prompt kept EXACTLY as provided (including schema & rigor rules) <<<
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

# ------------------------ Freesound integration (optional) -------------------------
FREESOUND_API_KEY = os.getenv("FREESOUND_API_KEY")

async def get_freesound_url(query: str) -> str:
    """
    Fetch an ambience sound URL from Freesound based on a mood query.
    Returns a direct MP3 preview URL when available, else "".
    """
    if not FREESOUND_API_KEY or not query or httpx is None:
        return ""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://freesound.org/apiv2/search/text/",
                params={
                    "query": query,
                    "filter": "duration:[5 TO 60]",
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
        print(f"[Freesound] Error fetching sound: {e}")
    return ""

# ---------------- Storyboard (inline SVG) --------
def _mood_color(mood_words):
    palette = ["#cfe3ff", "#e2d2ff", "#ffd6d6", "#c9f7da", "#ffe3c7", "#fde58a", "#e6e9ef"]
    seed_src = (",".join(mood_words) if mood_words else "cinematic")[:64]
    idx = int(hashlib.sha256(seed_src.encode("utf-8")).hexdigest(), 16) % len(palette)
    return palette[idx]

def _wrap_lines(text: str, max_len: int = 42):
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        test = w if not cur else f"{cur} {w}"
        if len(test) > max_len:
            if cur: lines.append(cur)
            cur = w
        else:
            cur = test
    if cur: lines.append(cur)
    return lines[:3]

def _is_female(text: str) -> bool:
    t = f" {text.lower()} "
    if any(k in t for k in [" she ", " her ", "woman", "girl", "female"]):
        return True
    if any(k in t for k in ["natalia", "natasha", "elena", "isabel", "maria", "anna"]):
        return True
    if any(k in t for k in ["dress", "gown", "heels", "silk gown", "evening dress"]):
        return True
    return False

def _infer_layout(caption: str):
    t = f" {caption.lower()} "
    if any(k in t for k in ["close-up"," close up "," closeup "," cu "]): size = "cu"
    elif any(k in t for k in ["medium"," mid "," two-shot"," two shot"," ms "]): size = "ms"
    else: size = "ws"
    two = any(k in t for k in ["conversation","talk","speaks","argue","confront","dialogue","both","two","exchange"])
    pos_primary = 0.25 if " left " in t else (0.75 if " right " in t else 0.5)
    pos_secondary = 0.75 if pos_primary < 0.5 else 0.25
    if any(k in t for k in ["low angle","looks up","towering"]): horizon = 0.68
    elif any(k in t for k in ["high angle","overhead","looks down"]): horizon = 0.38
    else: horizon = 0.56
    subj = "person"
    bg = "room"
    if any(k in t for k in ["city","skyline","rooftop","terrace"]): bg = "city"
    elif "garage" in t: bg = "garage"
    elif any(k in t for k in ["train","carriage","compartment"]): bg = "train"
    props = {
        "chandelier": any(k in t for k in ["chandelier", "ceiling light"]),
        "table": any(k in t for k in ["table","desk","bar","counter"]),
        "sofa": any(k in t for k in ["sofa","couch","booth"]),
        "door": any(k in t for k in ["door","exit","archway"]),
        "window": any(k in t for k in ["window","balcony","pane"]),
    }
    action_scan = any(k in t for k in ["scan","scans","survey","looks around","glance around","observes"])
    return size, two, pos_primary, pos_secondary, horizon, subj, bg, props, action_scan

def _female_silhouette(cx, baseline, scale=1.0, scan_pose=False):
    dark = "#081c44"
    r = int(11*scale)
    torso_w = int(24*scale); torso_h = int(40*scale)
    skirt_w = int(34*scale); skirt_h = int(24*scale)
    leg = int(18*scale)
    head_y = baseline - torso_h - skirt_h - r*2 + 8
    parts = [
        f'<circle cx="{cx}" cy="{head_y+r}" r="{r}" fill="{dark}" />',
        f'<circle cx="{cx+r-3}" cy="{head_y+4}" r="{int(5*scale)}" fill="{dark}" />',
        f'<rect x="{cx-torso_w//2}" y="{baseline-(torso_h+skirt_h)}" width="{torso_w}" height="{torso_h}" rx="5" fill="{dark}" />',
        f'<path d="M {cx-skirt_w//2} {baseline-skirt_h} L {cx+skirt_w//2} {baseline-skirt_h} L {cx+int(skirt_w*0.35)} {baseline} L {cx-int(skirt_w*0.35)} {baseline} Z" fill="{dark}"/>',
    ]
    if scan_pose:
        parts.append(f'<rect x="{cx+torso_w//2}" y="{baseline-(torso_h+skirt_h-16)}" width="{int(18*scale)}" height="{int(7*scale)}" rx="3" fill="{dark}" />')
        parts.append(f'<rect x="{cx-torso_w//2-int(18*scale)}" y="{baseline-(torso_h+skirt_h-4)}" width="{int(18*scale)}" height="{int(7*scale)}" rx="3" fill="{dark}" />')
    else:
        parts.append(f'<rect x="{cx-torso_w//2-int(16*scale)}" y="{baseline-(torso_h+skirt_h-8)}" width="{int(16*scale)}" height="{int(7*scale)}" rx="3" fill="{dark}" />')
        parts.append(f'<rect x="{cx+torso_w//2}" y="{baseline-(torso_h+skirt_h-8)}" width="{int(16*scale)}" height="{int(7*scale)}" rx="3" fill="{dark}" />')
    parts.append(f'<rect x="{cx-9*scale:.0f}" y="{baseline-6*scale:.0f}" width="{8*scale:.0f}" height="{leg}" rx="3" fill="{dark}" />')
    parts.append(f'<rect x="{cx+1*scale:.0f}" y="{baseline-6*scale:.0f}" width="{8*scale:.0f}" height="{leg}" rx="3" fill="{dark}" />')
    return "\n".join(parts)

def _neutral_silhouette(cx, baseline, scale=1.0):
    dark = "#081c44"
    r = int(11*scale)
    torso_w = int(26*scale); torso_h = int(40*scale)
    leg = int(18*scale)
    head_y = baseline - torso_h - r*2
    return "\n".join([
        f'<circle cx="{cx}" cy="{head_y+r}" r="{r}" fill="{dark}" />',
        f'<rect x="{cx-torso_w//2}" y="{baseline-torso_h}" width="{torso_w}" height="{torso_h}" rx="5" fill="{dark}" />',
        f'<rect x="{cx-torso_w//2-int(18*scale)}" y="{baseline-int(torso_h*0.75)}" width="{int(18*scale)}" height="{int(7*scale)}" rx="3" fill="{dark}" />',
        f'<rect x="{cx+torso_w//2}" y="{baseline-int(torso_h*0.75)}" width="{int(18*scale)}" height="{int(7*scale)}" rx="3" fill="{dark}" />',
        f'<rect x="{cx-9*scale:.0f}" y="{baseline-6*scale:.0f}" width="{8*scale:.0f}" height="{leg}" rx="3" fill="{dark}" />',
        f'<rect x="{cx+1*scale:.0f}" y="{baseline-6*scale:.0f}" width="{8*scale:.0f}" height="{leg}" rx="3" fill="{dark}" />',
    ])

def _draw_subject_person(cx, baseline, size, is_female, scan_pose):
    scale = 0.95 if size=="ws" else (1.3 if size=="ms" else 1.8)
    return _female_silhouette(cx, baseline, scale, scan_pose) if is_female else _neutral_silhouette(cx, baseline, scale)

def _draw_subject(subj, size, pos, w, h, is_female=False, scan_pose=False):
    cx = int(w * pos)
    base = int(h*0.74)
    if subj == "person":
        return _draw_subject_person(cx, base, size, is_female, scan_pose)
    return f'<rect x="{cx-20}" y="{base-28}" width="40" height="32" rx="6" fill="#081c44" opacity="0.7"/>'

def _room_box(w, h, horizon_y):
    vp_x = w//2
    lines = []
    lines.append(f'<rect x="12" y="12" width="{w-24}" height="{h-24}" fill="none" stroke="#0b2a55" stroke-width="2" opacity="0.35"/>')
    for x in range(24, w-24, 140):
        lines.append(f'<line x1="{x}" y1="{h-24}" x2="{vp_x}" y2="{horizon_y}" stroke="#0b2a55" stroke-width="1" opacity="0.25"/>')
    for y in range(horizon_y+10, h-24, 36):
        lines.append(f'<line x1="24" y1="{y}" x2="{w-24}" y2="{y}" stroke="#0b2a55" stroke-width="1" opacity="0.2"/>')
    return "\n".join(lines)

def _env_background(bg, w, h, horizon_y):
    if bg == "room":
        return _room_box(w, h, horizon_y)
    if bg == "city":
        blocks = []
        for x in range(40, w, 90):
            height = 40 + ((x*37) % 90)
            blocks.append(f'<rect x="{x}" y="{h-80-height}" width="26" height="{height}" fill="#0b2a55" opacity="0.12"/>')
        return "\n".join(blocks)
    if bg == "garage":
        cols = []
        for x in range(0, w, 160):
            cols.append(f'<rect x="{x+20}" y="{horizon_y-6}" width="16" height="{h-horizon_y+6}" fill="#0b2a55" opacity="0.15"/>')
        return "\n".join(cols)
    if bg == "train":
        return (
            f'<rect x="20" y="{horizon_y-50}" width="{w-40}" height="8" rx="4" fill="#0b2a55" opacity="0.2"/>'
            f'<rect x="24" y="{horizon_y-42}" width="{w-48}" height="{h-horizon_y-50}" rx="6" fill="#0b2a55" opacity="0.06"/>'
        )
    return ""

def _svg_storyboard_strings(caption: str, mood_words):
    bgcol = _mood_color(mood_words)
    lines = _wrap_lines(caption, 46)
    size, two, pos1, pos2, horizon, subj, bg, _props, action_scan = _infer_layout(caption)
    female = _is_female(caption)
    w, h = 960, 540
    horizon_y = int(h * horizon)
    thirds = (
        f'<line x1="{w/3}" y1="0" x2="{w/3}" y2="{h}" stroke="#7aa6ff" stroke-width="1" opacity="0.35"/>'
        f'<line x1="{2*w/3}" y1="0" x2="{2*w/3}" y2="{h}" stroke="#7aa6ff" stroke-width="1" opacity="0.35"/>'
        f'<line x1="0" y1="{h/3}" x2="{w}" y2="{h/3}" stroke="#7aa6ff" stroke-width="1" opacity="0.35"/>'
        f'<line x1="0" y1="{2*h/3}" x2="{w}" y2="{2*h/3}" stroke="#7aa6ff" stroke-width="1" opacity="0.35"/>'
    )
    env = _env_background(bg, w, h, horizon_y)
    subjects = _draw_subject(subj, size, pos1, w, h, is_female=female, scan_pose=action_scan)
    if two and subj == "person":
        subjects += _draw_subject(subj, size, pos2, w, h, is_female=not female, scan_pose=False)
    svg_markup = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{bgcol}"/>
      <stop offset="100%" stop-color="#ffffff"/>
    </linearGradient>
    <radialGradient id="v" cx="50%" cy="50%" r="70%">
      <stop offset="60%" stop-color="rgba(0,0,0,0)"/>
      <stop offset="100%" stop-color="rgba(0,0,0,0.18)"/>
    </radialGradient>
  </defs>
  <rect x="0" y="0" width="{w}" height="{h}" fill="url(#g)"/>
  <rect x="8" y="8" width="{w-16}" height="{h-16}" fill="none" stroke="#0a2150" stroke-width="3" rx="12"/>
  <rect x="0" y="0" width="{w}" height="{h}" fill="url(#v)"/>
  <g>{thirds}</g>
  <line x1="0" y1="{horizon_y}" x2="{w}" y2="{horizon_y}" stroke="#0a2150" stroke-width="2" opacity="0.28"/>
  <g>{env}</g>
  <g>{subjects}</g>
  <g font-family="ui-sans-serif,system-ui,Segoe UI,Roboto" fill="#0b2a55">
    <text x="24" y="42" font-size="26" font-weight="700">Storyboard</text>
    <text x="24" y="82" font-size="22">{(lines[0] if len(lines)>0 else "")}</text>
    <text x="24" y="112" font-size="22">{(lines[1] if len(lines)>1 else "")}</text>
    <text x="24" y="142" font-size="22">{(lines[2] if len(lines)>2 else "")}</text>
  </g>
</svg>'''
    data_url = "data:image/svg+xml;utf8," + quote(svg_markup, safe=":/,%#[]@!$&'()*+;=")
    return data_url, svg_markup

def _storyboard_from_beats(beats, mood_words, max_frames=4):
    frames = []
    for b in beats[:max_frames]:
        cap = (b.get("insight") or "").strip()
        if not cap:
            continue
        url, svg = _svg_storyboard_strings(cap, mood_words)
        frames.append({"caption": cap, "image_url": url, "svg": svg})
    return frames

def _image_prompt_from_caption(caption: str, summary: str, mood_words) -> str:
    mood = ", ".join(mood_words or [])[:80]
    return (
        "Storyboard frame, clean pencil sketch, cinematic composition, no text labels, "
        "high contrast, readable silhouettes, subtle shading, soft perspective lines. "
        f"Scene summary: {summary[:240]}. "
        f"Frame: {caption}. "
        f"Mood: {mood}. "
        "Style: professional storyboard artist, film pre‑viz, 3/4 view if helpful."
    )

# --------- OpenAI Images (optional) ----------
async def _gen_image_openai(prompt: str, size: str = "1536x1024") -> str:
    if not OPENAI_API_KEY:
        print("[Storyboard] OPENAI_API_KEY not set")
        return ""
    if httpx is None:
        print("[Storyboard] httpx not available")
        return ""

    SUPPORTED = {"1024x1024", "1536x1024", "1024x1536", "auto"}
    if size not in SUPPORTED:
        size = "1536x1024"

    async def _call(sz: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                r = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-image-1",
                        "prompt": prompt,
                        "size": sz,
                        "n": 1,
                    },
                )
                if r.status_code == 403:
                    print(f"[Storyboard] OpenAI 403 (access): {r.text[:400]}")
                    return ""
                if r.status_code >= 400:
                    print(f"[Storyboard] OpenAI error {r.status_code}: {r.text[:800]}")
                    return ""

                data = r.json()
                item = (data.get("data") or [{}])[0]

                b64 = item.get("b64_json")
                if b64:
                    return f"data:image/png;base64,{b64}"

                url = item.get("url")
                if url:
                    img = await client.get(url, timeout=90.0)
                    if img.status_code >= 400:
                        print(f"[Storyboard] OpenAI img fetch error {img.status_code}")
                        return ""
                    enc = base64.b64encode(img.content).decode("utf-8")
                    return f"data:image/png;base64,{enc}"

                print("[Storyboard] Image API returned neither b64_json nor url")
                return ""
        except Exception as e:
            print(f"[Storyboard] OpenAI generation error (size {sz}): {e}")
            return ""

    out = await _call(size)
    if not out and size != "1024x1024":
        out = await _call("1024x1024")
    return out

# --------- Stability (SDXL) Images (optional) ----------
def _stability_dims_from_size(size: str):
    if size == "1024x1536":
        return 704, 1024
    if size == "1536x1024":
        return 1024, 640
    return 1024, 1024

async def _gen_image_stability(prompt: str, size: str = "1536x1024") -> str:
    api_key = STABILITY_API_KEY
    if not api_key:
        print("[Storyboard] STABILITY_API_KEY not set")
        return ""
    if httpx is None:
        print("[Storyboard] httpx not available")
        return ""
    w, h = _stability_dims_from_size(size)
    payload = {
        "text_prompts": [{"text": prompt}],
        "cfg_scale": 7.0,
        "samples": 1,
        "steps": 30,
        "clip_guidance_preset": "FAST_GREEN",
        "width": w,
        "height": h,
    }
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(
                "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
            )
            if r.status_code >= 400:
                print(f"[Storyboard] Stability error {r.status_code}: {r.text[:800]}")
                return ""
            data = r.json()
            arts = data.get("artifacts") or []
            if not arts or not arts[0].get("base64"):
                print("[Storyboard] Stability returned no image")
                return ""
            return f"data:image/png;base64,{arts[0]['base64']}"
    except Exception as e:
        print(f"[Storyboard] Stability generation error: {e}")
        return ""

# --------- Prefer PNGs; embed inside inline SVG so UI shows them without changes ---
async def _maybe_generate_storyboard_pngs(obj: dict):
    if not STORYBOARD_ENABLE or STORYBOARD_PROVIDER == "off":
        return

    frames = obj.get("storyboard_frames") or []
    if not frames:
        return

    summary = obj.get("summary", "") or ""
    mood_words = (obj.get("theme") or {}).get("mood_words") or []
    targets = frames[: max(0, min(STORYBOARD_MAX_FRAMES, len(frames)))]

    def _svg_wrap_png(png_data_url: str, w: int = 960, h: int = 540) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<image href="{png_data_url}" x="0" y="0" width="{w}" height="{h}" preserveAspectRatio="xMidYMid slice"/>'
            '</svg>'
        )

    for f in targets:
        try:
            cap = (f.get("caption") or "").strip()
            if not cap:
                continue

            if isinstance(f.get("image_url"), str) and f["image_url"].startswith("data:image/png"):
                f["svg"] = _svg_wrap_png(f["image_url"])
                continue

            prompt = _image_prompt_from_caption(cap, summary, mood_words)
            data_url = ""
            if STORYBOARD_PROVIDER == "openai":
                data_url = await _gen_image_openai(prompt)
            elif STORYBOARD_PROVIDER == "stability":
                data_url = await _gen_image_stability(prompt)

            if data_url:
                f["image_url"] = data_url
                f["svg"] = _svg_wrap_png(data_url)
        except Exception as e:
            print(f"[Storyboard] Frame error: {e}")

    obj["storyboard_frames"] = frames

def _prune_output(obj: dict) -> dict:
    try:
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
        if isinstance(obj.get("analytics_signals"), list):
            obj["analytics_signals"] = obj["analytics_signals"][:5]
        if isinstance(obj.get("pacing_annotations"), list):
            obj["pacing_annotations"] = obj["pacing_annotations"][:8]
        if isinstance(obj.get("beat_markers"), list):
            obj["beat_markers"] = obj["beat_markers"][:5]
        if isinstance(obj.get("storyboard_frames"), list):
            obj["storyboard_frames"] = obj["storyboard_frames"][:6]

        pm = obj.get("pacing_map")
        if isinstance(pm, list) and len(pm) > 40:
            stride = max(1, len(pm) // 40)
            obj["pacing_map"] = pm[::stride][:40]
    except Exception:
        pass
    return obj

async def analyze_scene(scene: str) -> dict:
    raw = scene or ""
    clean = clean_scene(raw)

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
    if httpx is None:
        raise HTTPException(status_code=500, detail="Server missing dependency: httpx")

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
        json_mode_payload = dict(base_payload)
        json_mode_payload["response_format"] = {"type": "json_object"}
        try:
            data = await _post(json_mode_payload)
        except httpx.HTTPStatusError as e:
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

        obj.setdefault("summary", "Analysis")
        obj.setdefault("analytics", {})
        obj["analytics"].setdefault("mood", 60)
        obj["analytics"].setdefault("pacing", "Balanced")
        obj["analytics"].setdefault("realism", 70)
        obj["analytics"].setdefault("stakes", "Medium")
        obj["analytics"].setdefault("dialogue_naturalism", "Mixed")
        obj["analytics"].setdefault("cinematic_readiness", "Draft")
        obj.setdefault("analytics_signals", [])
        obj.setdefault("confidence", 60)
        obj.setdefault("confidence_reason", "Moderate clarity; limited conflicting signals.")
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
        obj.setdefault("pacing_annotations", [])
        obj.setdefault("beat_markers", [])
        obj.setdefault("growth_suggestions", [])
        obj.setdefault(
            "disclaimer",
            "This is a first‑pass cinematic analysis to support your craft. Your voice and choices always come first.",
        )
        obj.setdefault("storyboard_frames", [])

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
            print(f"[Freesound] Non-fatal: {_e}")

        try:
            if not obj.get("storyboard_frames"):
                mood_words = (obj.get("theme") or {}).get("mood_words") or []
                obj["storyboard_frames"] = _storyboard_from_beats(obj.get("beats") or [], mood_words, max_frames=4)
        except Exception as _e:
            print(f"[Storyboard] Non-fatal SVG: {_e}")

        obj = _prune_output(obj)

        try:
            await _maybe_generate_storyboard_pngs(obj)
        except Exception as _e:
            print(f"[Storyboard] Non-fatal generation issue: {_e}")

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
