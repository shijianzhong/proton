from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class AssessmentResult:
    should_auto_create: bool
    score: float
    confidence: float
    reasons: List[str]
    suggested_skill_name: str
    estimated_value_score: float
    risk_level: str
    signals: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_auto_create": self.should_auto_create,
            "score": self.score,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "suggested_skill_name": self.suggested_skill_name,
            "estimated_value_score": self.estimated_value_score,
            "risk_level": self.risk_level,
            "signals": dict(self.signals),
        }


class ValueAssessor:
    """
    Configurable value assessor for artifact auto-creation decisions.

    Environment variables:
    - ARTIFACT_AUTO_CREATE_ENABLED (default: false)
    - ARTIFACT_AUTO_CREATE_MIN_SCORE (default: 0.70)
    - ARTIFACT_ASSESS_REPEAT_TARGET (default: 3)
    - ARTIFACT_ASSESS_SUCCESS_TARGET (default: 0.85)
    - ARTIFACT_ASSESS_TOOL_CALL_TARGET (default: 4)
    - ARTIFACT_ASSESS_DURATION_TARGET_SEC (default: 2.0)
    """

    def __init__(self) -> None:
        cfg = self._load_file_config()
        self.auto_create_enabled = self._cfg_bool(cfg, "auto_create_enabled", "ARTIFACT_AUTO_CREATE_ENABLED", False)
        self.min_score = self._cfg_float(cfg, "min_score", "ARTIFACT_AUTO_CREATE_MIN_SCORE", 0.70)
        self.repeat_target = max(1, int(self._cfg_float(cfg, "repeat_target", "ARTIFACT_ASSESS_REPEAT_TARGET", 3)))
        self.success_target = min(1.0, max(0.0, self._cfg_float(cfg, "success_target", "ARTIFACT_ASSESS_SUCCESS_TARGET", 0.85)))
        self.tool_call_target = max(1, int(self._cfg_float(cfg, "tool_call_target", "ARTIFACT_ASSESS_TOOL_CALL_TARGET", 4)))
        self.duration_target_sec = max(0.1, self._cfg_float(cfg, "duration_target_sec", "ARTIFACT_ASSESS_DURATION_TARGET_SEC", 2.0))

    def assess(
        self,
        *,
        task_summary: str,
        signals: Dict[str, Any],
    ) -> AssessmentResult:
        repeat_count = max(0, int(signals.get("repeat_count") or 0))
        tool_call_count = max(0, int(signals.get("tool_call_count") or 0))
        failure_rate = self._safe_float(signals.get("failure_rate"), 1.0)
        success_rate = min(1.0, max(0.0, 1.0 - failure_rate))
        avg_duration_sec = max(0.0, self._safe_float(signals.get("avg_duration_sec"), 0.0))
        explicit_save = bool(
            signals.get("user_explicit_save")
            or signals.get("strong_signal")
            or str(signals.get("precipitation_level", "")).upper() == "L3"
        )

        # Weighted score (kept aligned with v2 requirements narrative)
        score = 0.0
        reasons: List[str] = []
        repeat_ok = repeat_count >= self.repeat_target
        success_ok = success_rate >= self.success_target
        tool_ok = tool_call_count >= self.tool_call_target
        duration_ok = avg_duration_sec >= self.duration_target_sec

        if repeat_ok:
            score += 0.30
            reasons.append(f"repeat_count={repeat_count} >= {self.repeat_target}")
        if success_ok:
            score += 0.25
            reasons.append(f"success_rate={success_rate:.3f} >= {self.success_target:.2f}")
        if tool_ok:
            score += 0.15
            reasons.append(f"tool_call_count={tool_call_count} >= {self.tool_call_target}")
        if duration_ok:
            score += 0.10
            reasons.append(f"avg_duration_sec={avg_duration_sec:.3f} >= {self.duration_target_sec:.1f}")
        if explicit_save:
            score += 0.20
            reasons.append("explicit_save_or_L3_signal=true")

        score = round(min(1.0, max(0.0, score)), 6)
        confidence = round(0.5 + score * 0.5, 6)
        should_auto_create = (
            self.auto_create_enabled
            and score >= self.min_score
            and repeat_ok
            and success_ok
        )
        if not self.auto_create_enabled:
            reasons.append("auto_create_disabled_by_config")
        elif score < self.min_score:
            reasons.append(f"score={score:.3f} < min_score={self.min_score:.2f}")

        risk_level = "low"
        if failure_rate >= 0.20:
            risk_level = "high"
        elif failure_rate >= 0.10:
            risk_level = "medium"

        return AssessmentResult(
            should_auto_create=should_auto_create,
            score=score,
            confidence=confidence,
            reasons=reasons,
            suggested_skill_name=self._suggest_skill_name(task_summary),
            estimated_value_score=score,
            risk_level=risk_level,
            signals={
                "repeat_count": repeat_count,
                "tool_call_count": tool_call_count,
                "success_rate": success_rate,
                "failure_rate": failure_rate,
                "avg_duration_sec": avg_duration_sec,
                "explicit_save": explicit_save,
            },
        )

    @staticmethod
    def _suggest_skill_name(task_summary: str) -> str:
        text = (task_summary or "").strip().lower()
        buf: List[str] = []
        for ch in text:
            if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"):
                buf.append(ch)
            elif buf and buf[-1] != "_":
                buf.append("_")
        name = "".join(buf).strip("_")
        return (name[:48] or "auto_generated_skill") + "_skill"

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    @staticmethod
    def _load_file_config() -> Dict[str, Any]:
        path = os.environ.get("ARTIFACT_ASSESS_CONFIG_PATH", "").strip()
        if not path:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _cfg_bool(cfg: Dict[str, Any], key: str, env_name: str, default: bool) -> bool:
        if key in cfg:
            return bool(cfg[key])
        return ValueAssessor._env_bool(env_name, default)

    @staticmethod
    def _cfg_float(cfg: Dict[str, Any], key: str, env_name: str, default: float) -> float:
        if key in cfg:
            try:
                return float(cfg[key])
            except (TypeError, ValueError):
                return default
        return ValueAssessor._env_float(env_name, default)
