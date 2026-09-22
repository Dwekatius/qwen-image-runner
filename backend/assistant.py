"""Qwen Image Runner — optional prompt assistant (DeepSeek).

When enabled, a chat message is first sent to the assistant. It decides whether the user
wants a new image, an edit of the previous one, or just an answer — and writes the actual
image prompt. The image model receives the assistant's prompt, not the raw request.
"""
from __future__ import annotations

import json
import re

import httpx

SYSTEM_PROMPT = """You are the prompt engineer behind a local Qwen-Image-2.1 image model.
The user talks naturally; you turn that into the best possible image instruction.

Reply with STRICT JSON only (no markdown fences), using exactly this schema:
{"action": "generate" | "edit" | "chat",
 "prompt": "<image prompt, empty when action is chat>",
 "reply": "<short human sentence, optional when a prompt is given>"}

Rules:
- "generate": the user wants a new image. Write a rich, concrete English prompt with
  subject, composition, lighting, mood, style and quality hints. 30-80 words.
- "edit": the user wants to change the image that was just produced. Write ONE clear
  English instruction that keeps everything the user did not mention.
- "chat": the user is asking a question, brainstorming or chatting. Answer briefly in
  "reply" and leave "prompt" empty.
- Use "edit" only when an image already exists in the conversation.
- Keep the user's ideas; always write the prompt in English.
- If the request is vague, make tasteful concrete choices instead of asking questions.
"""


def config_ok(settings: dict) -> bool:
    cfg = settings.get("assistant") or {}
    return bool(cfg.get("enabled") and (cfg.get("api_key") or "").strip())


def _endpoint(settings: dict) -> tuple[str, str, str]:
    cfg = settings.get("assistant") or {}
    base = (cfg.get("base_url") or "https://api.deepseek.com").rstrip("/")
    return base, (cfg.get("model") or "deepseek-chat").strip(), (cfg.get("api_key") or "").strip()


def build_messages(history: list[dict], user_text: str, has_last_image: bool) -> list[dict]:
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


async def run(settings: dict, history: list[dict], user_text: str, has_last_image: bool) -> dict:
    """Ask the assistant for the image prompt (or a plain reply)."""
    content = await complete(settings, build_messages(history, user_text, has_last_image))
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
