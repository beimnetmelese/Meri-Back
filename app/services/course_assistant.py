import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Document, DocumentChunk
from app.schemas.chat import CitationItem
from app.services.ai.embeddings import get_embedding
from app.services.ai.orchestrator import ai_orchestrator

logger = logging.getLogger(__name__)


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = sum(a * a for a in v1) ** 0.5
    mag2 = sum(b * b for b in v2) ** 0.5
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


class CourseAssistantService:
    @classmethod
    async def retrieve_relevant_chunks(
        cls,
        db: AsyncSession,
        platform_id: str,
        query: str,
        course_id: str | None = None,
        top_k: int = 4,
    ) -> list[tuple[DocumentChunk, str, float]]:
        """
        Retrieves top-k relevant course chunks for the platform and authorized course.
        Returns list of (DocumentChunk, document_title, score).
        """
        query_vector = await get_embedding(query)

        # Build query
        stmt = (
            select(DocumentChunk, Document.title)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(DocumentChunk.platform_id == platform_id)
        )
        if course_id:
            stmt = stmt.where(DocumentChunk.course_id == course_id)

        result = await db.execute(stmt)
        rows = result.all()

        scored_chunks = []
        for chunk, doc_title in rows:
            chunk_vec = chunk.embedding
            score = 0.0
            if chunk_vec and isinstance(chunk_vec, list):
                score = cosine_similarity(query_vector, chunk_vec)
            else:
                # Text keyword overlap fallback
                words = set(query.lower().split())
                c_words = set(chunk.content.lower().split())
                overlap = len(words.intersection(c_words))
                score = overlap / max(1, len(words))

            scored_chunks.append((chunk, doc_title, score))

        # Sort descending by score
        scored_chunks.sort(key=lambda x: x[2], reverse=True)
        return scored_chunks[:top_k]

    @classmethod
    async def answer_course_question(
        cls,
        db: AsyncSession,
        platform_id: str,
        question: str,
        course_id: str | None = None,
        language: str = "en",
        page_context: dict[str, Any] | None = None,
    ) -> tuple[str, str, list[CitationItem]]:
        """
        Answers course inquiry using grounded RAG and institution document records.
        Returns (response_text, provider_used, citations_list).
        """
        # Retrieve chunks
        relevant_items = await cls.retrieve_relevant_chunks(
            db=db,
            platform_id=platform_id,
            query=question,
            course_id=course_id,
            top_k=4,
        )

        context_list = []
        citations = []

        # If page_context contains live lesson/course text from frontend, prioritize as primary Source [1]
        has_page_context = False
        if page_context and isinstance(page_context, dict):
            raw_content = page_context.get("content", "")
            content_desc = ""
            if isinstance(raw_content, dict):
                content_desc = raw_content.get("text", "") or str(raw_content)
            elif isinstance(raw_content, str):
                content_desc = raw_content

            if content_desc:
                has_page_context = True
                page_title = page_context.get("title", "Current Webpage Context")
                context_list.insert(
                    0,
                    {
                        "title": f"Student Active Webpage ({page_title})",
                        "content": str(content_desc),
                        "page_number": None,
                    },
                )
                citations.insert(
                    0,
                    CitationItem(
                        document_title=page_title,
                        page_number=None,
                        section_or_lesson="Active Webpage",
                        source_reference="Current Active Page",
                        snippet=content_desc[:250] + ("..." if len(content_desc) > 250 else ""),
                    ),
                )

        # Only add DB knowledge chunks if they are actually relevant or if no page context is present
        min_score = 0.5 if (has_page_context and not course_id) else 0.15
        for chunk, doc_title, score in relevant_items:
            if score < min_score:
                continue
            context_list.append(
                {
                    "title": doc_title,
                    "content": chunk.content,
                    "page_number": chunk.page_number,
                    "section": chunk.section_title,
                }
            )
            citations.append(
                CitationItem(
                    document_title=doc_title,
                    page_number=chunk.page_number,
                    section_or_lesson=chunk.section_title or "Course Content",
                    source_reference=f"{doc_title} (Sec: {chunk.section_title or 'General'})",
                    snippet=chunk.content[:200] + ("..." if len(chunk.content) > 200 else ""),
                )
            )

        system_instruction = (
            "You are BridgeMate, an AI learning assistant helping a student on their educational platform. "
            "The student's CURRENT webpage content, active course, and current week/module are provided in the grounded context. "
            "You MUST answer questions directly using the student's active page and week content. "
            "When the student asks what is on this page, what week they are on, what deliverables or assignments are due, "
            "or asks for an explanation or summary of their current course, give a direct, friendly, and specific answer referencing the active section and deliverables. "
            "Do NOT reference unrelated courses (like Python or Django) unless specifically asked about them."
        )

        response_text, provider = await ai_orchestrator.generate_response(
            question=question,
            context=context_list,
            language=language,
            system_instruction=system_instruction,
        )

        return response_text, provider, citations


course_assistant_service = CourseAssistantService()
