from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class ErrorAnalysis:
    error_type: str
    is_fixable_by_llm: bool
    context_for_fix: str
    suggested_fix_prompt: str


class SkillErrorAnalyzer:
    """Classify tool/skill errors for safe auto-revision triggering."""

    FIXABLE_TYPES = ("typeerror", "valueerror", "syntaxerror")

    def analyze(self, *, error_text: str, tool_name: str) -> ErrorAnalysis:
        text = (error_text or "").strip()
        lower = text.lower()
        error_type = self._detect_error_type(lower)
        fixable = error_type in self.FIXABLE_TYPES
        context_for_fix = (
            f"tool={tool_name}\n"
            f"error_type={error_type or 'unknown'}\n"
            f"error_message={text[:500]}"
        )
        suggested = (
            "修复参数校验、类型转换和边界检查；补充防御式错误处理。"
            if fixable
            else "外部依赖错误或非代码逻辑问题，建议人工排查。"
        )
        return ErrorAnalysis(
            error_type=error_type or "unknown",
            is_fixable_by_llm=fixable,
            context_for_fix=context_for_fix,
            suggested_fix_prompt=suggested,
        )

    @staticmethod
    def _detect_error_type(lower: str) -> str:
        mapping: Dict[str, str] = {
            "typeerror": "typeerror",
            "valueerror": "valueerror",
            "syntaxerror": "syntaxerror",
            "timeout": "timeout",
            "network": "network",
            "apierror": "apierror",
        }
        for key, value in mapping.items():
            if key in lower:
                return value
        return ""
