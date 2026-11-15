import logging
from typing import Any

import httpx

from app.core.config import settings
from app.services.ai.base import BaseAIProvider

logger = logging.getLogger(__name__)


class GroqProvider(BaseAIProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = model or settings.GROQ_MODEL
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    async def generate(
        self,
        question: str,
        context: list[dict[str, Any]],
        language: str = "en",
        system_instruction: str | None = None,
    ) -> str:
        if not self.api_key:
            raise ValueError("Groq API key is not configured.")

        lang_prompt = (
            "You MUST respond in Amharic (አማርኛ) using clear and accessible language."
            if language == "am"
            else "You MUST respond in clear English."
        )

        formatted_context = ""
        if context:
            formatted_context = "--- GROUNDED CONTEXT FROM INSTITUTION ---\n"
            for i, c in enumerate(context, 1):
                title = c.get("title", f"Source {i}")
                content = c.get("content", "")
                page = c.get("page_number")
                page_str = f" (Page {page})" if page else ""
                formatted_context += f"[{i}] {title}{page_str}:\n{content}\n\n"
            formatted_context += "--- END CONTEXT ---\n"

        system_msg = (
            "You are BridgeMate, an AI learning and career assistant embedded in an educational/job platform. "
            "You are helpful, empathetic, and grounded. "
            "Base your answers strictly on the provided grounded context. "
            "If the context does not contain enough information to answer reliably, state that clearly. "
            "Never invent facts or claim to know employer hiring decisions. "
            f"{lang_prompt}\n{system_instruction or ''}"
        )

        user_msg = f"{formatted_context}\nLearner's Question: {question}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "BridgeMate-AI/1.0",
        }
        candidate_models = ["qwen/qwen3.8-27b", self.model, "openai/gpt-oss-120b", "llama-3.3-70b-versatile"]
        # Deduplicate while preserving order
        candidate_models = list(dict.fromkeys(filter(None, candidate_models)))

        async with httpx.AsyncClient(timeout=15.0) as client:
            last_err = None
            for model_name in candidate_models:
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                }
                resp = await client.post(self.base_url, headers=headers, json=payload)
                if resp.status_code == 200:
                    self.model = model_name  # Cache working model for future calls
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "").strip()
                elif resp.status_code == 404 or "model_not_found" in resp.text:
                    logger.warning(f"Groq model '{model_name}' not accessible, trying fallback model...")
                    last_err = resp.text
                    continue
                else:
                    logger.error(f"Groq API error on model {model_name}: {resp.status_code} - {resp.text}")
                    last_err = resp.text
                    break

            raise RuntimeError(f"Groq API error across candidate models: {last_err}")
