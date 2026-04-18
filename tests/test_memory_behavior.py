import pathlib
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.core.models import PortalMemoryEntry
from src.portal.memory_behavior import MemoryBehaviorEngine


def _m(
    memory_id: str,
    *,
    memory_type: str = "fact",
    confidence_tier: str = "medium",
    confidence_score: float = 0.7,
    conflict_status: str = "none",
    tags=None,
):
    return PortalMemoryEntry(
        id=memory_id,
        portal_id="p1",
        user_id="u1",
        content="test",
        memory_type=memory_type,
        confidence_tier=confidence_tier,
        confidence_score=confidence_score,
        conflict_status=conflict_status,
        tags=tags or [],
        created_at=datetime.now(),
        last_accessed=datetime.now(),
    )


def test_memory_behavior_engine_generates_conflict_and_preference_suggestions():
    engine = MemoryBehaviorEngine()
    memories = [
        _m("m1", conflict_status="pending"),
        _m("m2", memory_type="preference", tags=["写作偏好"]),
        _m("m3", confidence_tier="low", confidence_score=0.3),
        _m("m4", confidence_tier="low", confidence_score=0.4),
        _m("m5", confidence_tier="low", confidence_score=0.2),
    ]
    suggestions = engine.suggest(memories=memories, user_message="帮我回复客户")
    codes = {item["code"] for item in suggestions}
    assert "memory_conflict_confirmation" in codes
    assert "memory_preference_apply" in codes
    assert "memory_low_confidence_guard" in codes
