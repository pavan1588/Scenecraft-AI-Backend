# SceneCraft Scene Editor

**SceneCraft Scene Editor** is a FastAPI-based backend that provides intelligent, example-based scene rewriting suggestions. It is part of the SceneCraft AI suite, integrated with the cinematic intelligence of the Scene Analyzer and enhanced with professional screenwriting principles.

---

## 🎯 What It Does

- Analyzes 1–2 page scenes (max 600 words)
- Suggests rewrites only where necessary
- Praises strong lines with clear rationale
- Offers examples and explanations for rewrites
- Finishes with a **natural language Suggestions** section
- Never shows internal prompt logic to the user

---

## 🔍 Key Features

- Integrated with OpenRouter AI (Mistral model)
- Built-in rate limiting (10 calls/min per IP)
- CORS-enabled for frontend use
- Modular prompt design (easy to update)
- Honors Terms & Conditions requirement

---

## 🧠 Built on Professional Insights

- SceneCraft AI Benchmarks (pacing, subtext, visual grammar, etc.)
- Christopher McQuarrie’s rewrite-first mindset
- Steven Pinker’s clarity principles
- Eric Roth’s discipline-first rewriting
- Stanford’s characterization models
- NoFilmSchool’s pro-level scene architecture

---

## 📦 API Endpoint

### `POST /edit`

**Request body:**
```json
{
  "scene": "INT. OFFICE – NIGHT\nJohn stares at the letter in disbelief..."
}
