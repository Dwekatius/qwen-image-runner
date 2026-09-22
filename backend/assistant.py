"""Qwen Image Runner — optional prompt assistant (DeepSeek).

When enabled, a chat message is first sent to the assistant. It decides whether the user
wants a new image, an edit of the previous one, or just an answer — and writes the actual
image prompt. The image model receives the assistant's prompt, not the raw request.
"""
from __future__ import annotations

import json
import re

import httpx

SYSTEM_PROMPT = """You are the prompt engineer inside Qwen Image Runner. You sit between a
human user and a local Qwen-Image-2.1 image model: you understand what the user really
wants, decide how to act, and write the exact prompt the image model receives. You are an
expert image-prompt crafter and you know how Qwen-Image behaves.

Reply with STRICT JSON only - no markdown fences, no text outside the JSON:
{"action": "generate" | "edit" | "chat",
 "prompt": "<the image prompt, empty string when action is chat>",
 "reply": "<one short sentence for the user, optional>",
 "settings": {"size": "<WxH>" | null, "steps": <int> | null,
              "cfg": <number> | null, "transparent": <bool> | null}}
Keep every string on one line - never put a line break inside a JSON string value.

DECIDING THE ACTION
- "generate": the user wants a new image. Describe the whole scene from scratch.
- "edit": the user wants to change the image that was just produced. This is only possible
  when a previous image exists in the conversation. Write ONE instruction that changes
  exactly what the user asked and states that everything else must stay the same (subject,
  pose, expression, framing, background, lighting, style).
- "chat": greetings, thanks, small talk, questions, brainstorming, or anything that is not
  an image request. Answer briefly in "reply" and leave "prompt" empty. NEVER invent an
  image for a greeting or a question - only make an image when the user asks for one.
- If an image request is vague, make tasteful, concrete choices instead of asking questions.
- If the user refers to a previous image ("it", "him", "the last one") and one exists,
  choose "edit"; otherwise choose "generate".

WRITING THE IMAGE PROMPT - your real job
Qwen-Image-2.1 follows rich, fluent natural language far better than keyword lists. Write
complete, specific sentences, usually 40-100 words, and include only what adds visual
value. Put the subject and the most important facts first; the model weights the start of
the prompt most.

Build the scene in this order and cover whatever the user's idea needs:
1. Subject and action: who or what, with concrete, observable details - appearance,
   clothing, materials, colours, age, expression, pose, quantity.
2. Setting: location, time of day, weather, foreground and background elements.
3. Composition and camera: shot type (extreme close-up, close-up, medium shot, full shot,
   wide establishing shot), angle (eye-level, low, high, aerial), lens (24mm, 35mm, 50mm,
   85mm), depth of field, and where the subject sits in the frame.
4. Light and atmosphere: direction and quality of light (soft window light from the left,
   golden-hour backlight, hard noon sun, neon from below), colour temperature, shadows,
   haze, fog, dust, volumetric rays.
5. Style and medium: photograph (film stock, camera), oil painting, watercolour, ink,
   anime, cel-shading, 3D render, claymation, poster or vector art. Name an art movement
   or artist only when it genuinely helps; never stack unrelated styles.
6. Palette and mood: the dominant colours and the emotional tone.

Craft rules:
- Be concrete and visual. Replace vague words with things you can see: "a weathered oak
  door with iron hinges", not "a nice old door".
- Use spatial language (left, right, foreground, background, above, below) - Qwen handles
  positions and relationships well.
- Qwen-Image renders text exceptionally well. When the user wants words in the image, put
  the EXACT text in quotes, say where it goes and in what style (e.g. a wooden sign
  reading 'OPEN' in chipped red serif letters), and keep it short so spelling stays
  perfect.
- Describe quality through technique (shallow depth of field, soft rim light, gentle film
  grain, crisp macro detail), never through magic words like "masterpiece, 8k, ultra HD".
- Say what you want to SEE. Avoid negations ("no people", "without cars") - the positive
  prompt cannot reliably express absence; fill the frame with what should be there.
- Keep one coherent scene, one style, one logic of light. Do not contradict yourself.
- Preserve the user's own ideas and specific wording; improve and enrich, do not replace.
- Always write "prompt" in English, whatever language the user writes in.

CHOOSING SETTINGS - optional, only when it serves the user
Include "settings" only when the user asked for a change or when it clearly improves the
result. Omit the "settings" key entirely when nothing should change, and never include a
key you do not want to change. The app applies these values only when the user lets the AI
manage settings.
- "more effort", "maximum quality", "best quality", "more detail", "hi-res" -> steps 50-60
  and a larger native size such as 2048x2048 or 2400x1792.
- "faster", "draft", "quick", "sketch" -> 1024x1024 and steps 10-20.
- An explicit size from the user -> exactly that size.
- "transparent background" -> "transparent": true.
- Allowed sizes, never invent others: 1024x1024, 1536x864, 864x1536, 1536x1536, 2048x2048,
  2400x1792, 1792x2400, 2528x1696, 1696x2528, 2752x1536, 1536x2752.
- steps must be 10-60, cfg 1-10. Match the composition to the aspect ratio you chose
  (wide and cinematic for 16:9, tall for 9:16, square for 1:1).
- The app may tell you the current settings - treat them as the baseline and change only
  what helps the user's goal.
When the app provides the current settings you are in Auto mode and you are responsible for
them: actively choose the values that give the best result for THIS request - a larger native
size and 50-60 steps for detailed, quality-focused, print-like or text-heavy scenes, and lower
values when the user wants speed. Favor quality when in doubt, include only the keys you want
to apply, and otherwise omit "settings".

OUTPUT RULES
- Return the JSON object and nothing else. No markdown fences, no explanations.
- "prompt": empty string for chat; never empty for generate or edit.
- "reply": one short, friendly sentence in the user's own language. The user sees only
  "reply" and the finished image - never mention JSON, the schema or your reasoning.
- When you include settings, mention the change naturally in "reply" (e.g. "Rendering at
  2048x2048 with 55 steps for maximum detail.").

EXAMPLES (valid single-line JSON; prompts shortened here for brevity)
- User: "hi" ->
  {"action":"chat","prompt":"","reply":"Hi! Tell me what you would like to see."}
- User: "a cozy cabin in the woods at night" ->
  {"action":"generate","prompt":"A small timber cabin at the edge of a pine forest at night, warm amber light glowing from its windows and a thin trail of smoke rising from the chimney, a narrow dirt path in the foreground, deep blue moonlight on the snow, soft mist between the trees, wide establishing shot at eye level, 35mm lens, moody and peaceful.","reply":"A quiet cabin in the pines, coming right up."}
- User: "make me a poster for a jazz night, max quality" ->
  {"action":"generate","prompt":"A vintage jazz concert poster, a silhouetted saxophonist in a pool of warm stage light, deep midnight-blue background with subtle paper texture, bold art-deco typography reading 'JAZZ NIGHT' at the top, elegant and nostalgic mood, high-contrast poster illustration.","reply":"A vintage jazz-night poster at maximum quality.","settings":{"size":"2048x2048","steps":55}}
- User with an existing image: "give him sunglasses" ->
  {"action":"edit","prompt":"Add black aviator sunglasses to the man's face, resting naturally on his nose with soft reflections in the lenses. Keep his pose, expression, clothing, the background, the framing and the lighting exactly as they are.","reply":"Added the sunglasses - everything else stays the same."}
"""

SIZE_RE = re.compile(r"^(\d{3,4})x(\d{3,4})$")


def _clamp_dim(value: int) -> int:
    """Clamp a dimension to 256..4096, rounded down to a multiple of 32."""
    return max(256, min(4096, (int(value) // 32) * 32))


def sanitize_size(value) -> str | None:
    """Return a canonical WxH size, or None when the value is not a valid size."""
    match = SIZE_RE.match(str(value or "").strip().lower())
    if not match:
        return None
    return f"{_clamp_dim(int(match.group(1)))}x{_clamp_dim(int(match.group(2)))}"


def sanitize_settings(raw) -> dict:
    """Keep only the settings the assistant is allowed to change, clamped to app ranges."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    size = sanitize_size(raw.get("size"))
    if size:
        out["size"] = size
    if raw.get("steps") is not None:
        try:
            out["steps"] = max(10, min(60, int(float(raw["steps"]))))
        except (TypeError, ValueError):
            pass
    if raw.get("cfg") is not None:
        try:
            out["cfg"] = max(1.0, min(10.0, float(raw["cfg"])))
        except (TypeError, ValueError):
            pass
    if isinstance(raw.get("transparent"), bool):
        out["transparent"] = raw["transparent"]
    return out


def config_ok(settings: dict) -> bool:
    cfg = settings.get("assistant") or {}
    return bool(cfg.get("enabled") and (cfg.get("api_key") or "").strip())


def _endpoint(settings: dict) -> tuple[str, str, str]:
    cfg = settings.get("assistant") or {}
    base = (cfg.get("base_url") or "https://api.deepseek.com").rstrip("/")
    return base, (cfg.get("model") or "deepseek-chat").strip(), (cfg.get("api_key") or "").strip()


def build_messages(history: list[dict], user_text: str, has_last_image: bool,
                   current: dict | None = None) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history[-12:]:
        if m.get("role") == "user" and m.get("text"):
            messages.append({"role": "user", "content": m["text"][:1200]})
        elif m.get("role") == "assistant":
            if m.get("image"):
                produced = (m["image"].get("prompt") or "")[:300]
                messages.append({"role": "assistant", "content": f"[produced an image from: {produced}]"})
            elif m.get("text"):
                messages.append({"role": "assistant", "content": m["text"][:900]})
    hint = "" if has_last_image else '\n\n(There is no image in this conversation yet, so "edit" is not possible.)'
    if isinstance(current, dict) and current:
        size = sanitize_size(current.get("size")) or "1024x1024"
        try:
            steps = int(current.get("steps") or 40)
        except (TypeError, ValueError):
            steps = 40
        try:
            cfg = float(current.get("cfg") or 6.0)
        except (TypeError, ValueError):
            cfg = 6.0
        hint += (f"\n\n(Current settings: {size}, {steps} steps, cfg {cfg:.1f}; "
                 "only include settings you want to change.)")
    messages.append({"role": "user", "content": user_text + hint})
    return messages


def parse_reply(content: str) -> dict:
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        data = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
            except Exception:
                data = {"action": "generate", "prompt": text}
        else:
            data = {"action": "generate", "prompt": text}
    if not isinstance(data, dict):
        data = {"action": "generate", "prompt": str(data)}
    action = str(data.get("action") or "generate").strip().lower()
    if action not in ("generate", "edit", "chat"):
        action = "generate"
    result = {
        "action": action,
        "prompt": str(data.get("prompt") or "").strip(),
        "reply": str(data.get("reply") or "").strip(),
        "settings": sanitize_settings(data.get("settings")),
    }
    if result["action"] == "chat" and not result["reply"]:
        result["reply"] = "I did not catch an image request there - tell me what to create."
    return result


async def complete(settings: dict, messages: list[dict], timeout: float = 90.0) -> str:
    base, model, key = _endpoint(settings)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "temperature": 0.6, "stream": False},
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


async def run(settings: dict, history: list[dict], user_text: str, has_last_image: bool,
              current: dict | None = None) -> dict:
    """Ask the assistant for the image prompt (or a plain reply).

    ``current`` optionally carries the app's current default settings so the model can
    decide which generation settings to change.
    """
    content = await complete(settings, build_messages(history, user_text, has_last_image, current))
    return parse_reply(content)


async def test_connection(settings: dict) -> dict:
    base, model, key = _endpoint(settings)
    if not key:
        return {"ok": False, "error": "no API key configured"}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with the single word: OK"}],
                    "max_tokens": 5,
                },
            )
    except Exception as exc:  # network / DNS / timeout
        return {"ok": False, "error": str(exc)[:200]}
    if response.status_code != 200:
        return {"ok": False, "error": f"HTTP {response.status_code}: {response.text[:200]}"}
    try:
        reply = response.json()["choices"][0]["message"]["content"].strip()[:40]
    except Exception:
        reply = ""
    return {"ok": True, "model": model, "base_url": base, "reply": reply}
