import logging
from typing import Any

from app.core.config import settings
from app.services.ai.gemini import GeminiProvider
from app.services.ai.groq import GroqProvider
from app.services.ai.offline_faq import OfflineFAQProvider

logger = logging.getLogger(__name__)


class AIOrchestrator:
    """
    Manages provider selection and automated fallback:
    Gemini -> Groq -> Offline FAQ.
    Maintains exact grounded context and security grounding across all provider switches.
    """

    def __init__(self):
        self.gemini = GeminiProvider()
        self.groq = GroqProvider()
        self.offline_faq = OfflineFAQProvider()

    async def generate_response(
        self,
        question: str,
        context: list[dict[str, Any]],
        language: str = "en",
        system_instruction: str | None = None,
    ) -> tuple[str, str]:
        """
        Executes fallback chain.
        Returns: Tuple of (generated_text, provider_name_used)
        """
        # 1. Try Gemini
        if settings.GEMINI_API_KEY and not settings.GEMINI_API_KEY.startswith("YOUR_"):
            try:
                res = await self.gemini.generate(
                    question=question,
                    context=context,
                    language=language,
                    system_instruction=system_instruction,
                )
                if res and res.strip():
                    return res, "gemini"
            except Exception as e:
                logger.warning(f"Gemini provider failed: {e}. Falling back to Groq.")

        # 2. Try Groq
        if settings.GROQ_API_KEY and not settings.GROQ_API_KEY.startswith("YOUR_"):
            try:
                res = await self.groq.generate(
                    question=question,
                    context=context,
                    language=language,
                    system_instruction=system_instruction,
                )
                if res and res.strip():
                    return res, "groq"
            except Exception as e:
                logger.warning(f"Groq provider failed: {e}. Falling back to Offline FAQ.")

        # 3. Fallback to Offline FAQ
        res = await self.offline_faq.generate(
            question=question,
            context=context,
            language=language,
            system_instruction=system_instruction,
        )
        return res, "offline_faq"


ai_orchestrator = AIOrchestrator()
