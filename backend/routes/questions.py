"""Phase 5: Questions Queue action endpoints.

POST /api/churches/{church_id}/questions/{question_id}/answer
  — record a human answer; optionally cascades to analytical answer generation.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException

from ..tools import question_store

router = APIRouter(prefix="/api/churches", tags=["questions-queue"])


def _generate_analytical_answer(query: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Cascade-driven analytical answer generation.

    Phase 5: rules-based stub using the guider cascade infrastructure to
    produce reasoning chain + confidence. Phase 6+ will replace with LLM.
    """
    try:
        from ..membrane.guiders.cascade import GuiderCascade
        # Construct a lightweight perturbation-like object.
        pert = type("P", (), {"signal_name": "QUESTION_ASKED", "payload": {"query": query, **context}})()
        cascade = GuiderCascade()
        result = cascade.evaluate(pert)
        verdicts = result.to_dict().get("verdicts", [])
        reasoning = "; ".join(v.get("rationale", "") for v in verdicts if v.get("rationale"))
        return {
            "answer": f"Analytical answer for: {query}",
            "confidence": 0.65,
            "reasoning": reasoning or "cascade produced no rationale",
            "source": "cascade",
        }
    except Exception as exc:
        return {
            "answer": f"(fallback) {query}",
            "confidence": 0.3,
            "reasoning": f"cascade unavailable: {exc!r}",
            "source": "fallback",
        }


@router.post("/{church_id}/questions/{question_id}/answer")
async def answer_question(
    church_id: str,
    question_id: str,
    body: Optional[Dict[str, Any]] = Body(default=None),
) -> Dict[str, Any]:
    body = body or {}
    answer_text = body.get("answer")
    answerer = body.get("answerer", "unknown")
    if not answer_text:
        # No human answer provided — generate analytical answer.
        existing = question_store.get_question(church_id, question_id)
        query = (existing or {}).get("query", body.get("query", ""))
        gen = _generate_analytical_answer(query, body.get("context", {}))
        rec = question_store.record_answer(
            church_id, question_id,
            answer=gen["answer"],
            answerer="cascade",
            confidence=gen["confidence"],
            reasoning=gen["reasoning"],
            source=gen["source"],
        )
        return {"ok": True, "question_id": question_id, "answer_record": rec, "generated": True}

    rec = question_store.record_answer(
        church_id, question_id,
        answer=str(answer_text),
        answerer=str(answerer),
        confidence=body.get("confidence"),
        reasoning=body.get("reasoning"),
        source="human",
    )
    return {"ok": True, "question_id": question_id, "answer_record": rec, "generated": False}
