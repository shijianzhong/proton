from __future__ import annotations

from typing import Any, Dict, List

from ..core.models import PortalMemoryEntry


class MemoryBehaviorEngine:
    """Generate low-risk behavior suggestions from retrieved memories."""

    def suggest(
        self,
        *,
        memories: List[PortalMemoryEntry],
        user_message: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        _ = user_message
        if not memories:
            return []

        suggestions: List[Dict[str, Any]] = []

        conflict_pending = [m for m in memories if str(m.conflict_status or "").lower() == "pending"]
        if conflict_pending:
            suggestions.append(
                {
                    "code": "memory_conflict_confirmation",
                    "title": "建议先确认冲突记忆",
                    "detail": f"检测到 {len(conflict_pending)} 条待确认冲突记忆，建议先澄清后再给确定性建议。",
                    "confidence": 0.82,
                    "action": "ask_clarification_first",
                }
            )

        low_conf = [
            m
            for m in memories
            if str(m.confidence_tier or "").lower() == "low" or float(m.confidence_score or 0.0) < 0.45
        ]
        if len(low_conf) >= 3:
            suggestions.append(
                {
                    "code": "memory_low_confidence_guard",
                    "title": "建议降低记忆依赖强度",
                    "detail": f"低置信记忆较多（{len(low_conf)} 条），回答中应降低断言强度并提示不确定性。",
                    "confidence": 0.74,
                    "action": "soften_claims",
                }
            )

        preference_like = [
            m
            for m in memories
            if str(m.memory_type or "").lower() in {"preference", "style", "habit"}
            or any("偏好" in str(tag) or "preference" in str(tag).lower() for tag in (m.tags or []))
        ]
        if preference_like:
            suggestions.append(
                {
                    "code": "memory_preference_apply",
                    "title": "建议优先应用用户偏好",
                    "detail": f"命中 {len(preference_like)} 条偏好类记忆，可优先按历史偏好组织表达。",
                    "confidence": 0.7,
                    "action": "apply_preference_first",
                }
            )

        return suggestions[: max(1, int(limit))]
