    # --- call OpenRouter with JSON mode, then fallback if unsupported ---
    base_payload = {
        "model": os.getenv("OPENROUTER_MODEL", "gpt-4o"),
        "temperature": 0.5,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": clean}
        ]
    }

    async def _post(payload):
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
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
                detail_text = e.response.text
            except Exception:
                pass
            if e.response.status_code in (400, 404, 422) or "response_format" in detail_text.lower():
                data = await _post(base_payload)
            else:
                raise

        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        ).strip()

        # Parse STRICT JSON if present
        import json as _json
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

        # Minimal defaults
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
