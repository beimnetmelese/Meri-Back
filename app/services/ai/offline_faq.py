import logging
import re
from typing import Any

from app.services.ai.base import BaseAIProvider

logger = logging.getLogger(__name__)

# Standard offline fallback answers when LLM APIs are unreachable
OFFLINE_KNOWLEDGE = [
    {
        "keywords": ["qualified", "requirements", "skills", "job", "apply"],
        "en": "To see if you are qualified, compare your current skills with the job requirements listed on this page. If you meet the essential technical requirements, we encourage you to submit your application with a tailored CV.",
        "am": "ብቁ መሆንዎን ለማረጋገጥ ችሎታዎትን በዚህ ገጽ ላይ ከተዘረዘሩት የስራ መስፈርቶች ጋር ያነፃፅሩ። መሰረታዊ መስፈርቶችን ካሟሉ ማመልከቻዎን በዝርዝር ሲቪ እንዲያቀርቡ እናበረታታለን።",
    },
    {
        "keywords": ["interview", "prepare", "mock", "practice"],
        "en": "Interview preparation tip: Review the core skills required for this position, practice explaining your relevant projects using the STAR method (Situation, Task, Action, Result), and be ready to discuss any technical challenges you overcame.",
        "am": "ለቃለ-መጠይቅ ዝግጅት ጠቃሚ ምክር፡ ለዚህ ስራ የሚያስፈልጉትን ዋና ችሎታዎች ይከልሱ እና ከዚህ ቀደም የሰሩዋቸውን ፕሮጀክቶች በግልጽ ለማስረዳት ይዘጋጁ።",
    },
    {
        "keywords": ["lesson", "explain", "summarize", "course", "assignment"],
        "en": "This lesson covers the fundamentals provided in your course material. Please review the highlighted concepts and consult the course syllabus or request human tutor assistance if you need further clarification.",
        "am": "ይህ ትምህርት በኮርሱ ይዘት ውስጥ የተካተቱትን መሰረታዊ ፅንሰ-ሀሳቦች ያብራራል። እባክዎ ዋና ዋና ነጥቦቹን ይከልሱ ወይም ተጨማሪ ማብራሪያ ከፈለጉ ከአስተማሪ እርዳታ ይጠይቁ።",
    },
    {
        "keywords": ["accommodation", "accessibility", "disability", "support"],
        "en": "BridgeMate supports interview and learning accommodations. You can submit a private accommodation request directly through the widget or platform settings.",
        "am": "ብሪጅሜት የትምህርት እና የቃለ-መጠይቅ ድጋፍ ፍላጎቶችን ያመቻቻል። በፕላትፎርሙ በኩል ሚስጥራዊ የድጋፍ ጥያቄ ማቅረብ ይችላሉ።",
    },
]


class OfflineFAQProvider(BaseAIProvider):
    """
    Offline fallback provider that strictly answers from verified FAQs and grounded context.
    Guarantees that the assistant stays responsive even if remote AI APIs fail.
    """

    async def generate(
        self,
        question: str,
        context: list[dict[str, Any]],
        language: str = "en",
        system_instruction: str | None = None,
    ) -> str:
        q_lower = question.lower()

        # If grounded context is provided (e.g., from course chunks or job details),
        # extract relevant sentences from it
        if context:
            matched_sentences = []
            words = set(re.findall(r"\w+", q_lower))
            for item in context:
                content = item.get("content", "")
                if isinstance(content, dict):
                    content = " ".join(str(v) for v in content.values())
                sentences = re.split(r"(?:[.!?]\s+|\n+)", str(content))
                for s in sentences:
                    s_clean = s.strip().lstrip("-•* ")
                    if not s_clean:
                        continue
                    s_words = set(re.findall(r"\w+", s_clean.lower()))
                    if words.intersection(s_words):
                        matched_sentences.append(s_clean)

            if matched_sentences:
                top_facts = ". ".join(matched_sentences[:3])
                if language == "am":
                    return f"ከተረጋገጠው የትምህርት ይዘት የተገኘ መረጃ፡ {top_facts}።"
                return f"Based on verified course/job records: {top_facts}."

        # Search offline pre-approved FAQs
        for entry in OFFLINE_KNOWLEDGE:
            for kw in entry["keywords"]:
                if kw in q_lower:
                    return entry.get(language, entry["en"])

        if language == "am":
            return "ይቅርታ፣ በወቅቱ ከዋናው AI አቅራቢ ጋር መገናኘት አልተቻለም። እባክዎን ጥያቄዎን በድጋሚ ይሞክሩ ወይም የሰው ድጋፍ (Human Support) ይጠይቁ።"
        return "The remote AI provider is temporarily unreachable, and no verified offline answer matched your query. Please request human support or try again shortly."
