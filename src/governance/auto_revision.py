from __future__ import annotations

import json
import logging
import os
from typing import Optional

from .error_analyzer import SkillErrorAnalyzer
from ..core.models import ArtifactRolloutStatus, ToolResult
from ..execution.tool_executor import ToolExecutionRequest, ToolExecutionSlice

logger = logging.getLogger(__name__)


class AutoSkillRevisionSlice(ToolExecutionSlice):
    """
    Lightweight R2 phase-1: trigger revision candidate creation on fixable skill errors.
    """

    def __init__(
        self,
        *,
        enabled: Optional[bool] = None,
        max_per_execution: int = 2,
        auto_grayscale: Optional[bool] = None,
    ):
        self.enabled = (
            enabled
            if enabled is not None
            else str(os.environ.get("AUTO_SKILL_REVISION_ENABLED", "false")).strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.auto_grayscale = (
            auto_grayscale
            if auto_grayscale is not None
            else str(os.environ.get("AUTO_SKILL_REVISION_AUTO_GRAYSCALE", "false")).strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.max_per_execution = max(1, int(max_per_execution))
        self._analyzer = SkillErrorAnalyzer()

    async def before_execute(self, request: ToolExecutionRequest) -> Optional[ToolResult]:
        _ = request
        return None

    async def after_execute(self, request: ToolExecutionRequest, result: ToolResult) -> ToolResult:
        if not self.enabled:
            return result
        if request.tool.source != "skill":
            return result
        if not self._is_failed_result(result):
            return result
        if self._is_call_already_triggered(request):
            return result
        if not self._consume_quota(request):
            return result

        error_text = self._extract_error_text(result)
        analysis = self._analyzer.analyze(error_text=error_text, tool_name=request.tool.name)
        if not analysis.is_fixable_by_llm:
            return result

        from ..artifacts import get_artifact_factory_service
        factory = get_artifact_factory_service()
        parent_candidate_id = await self._resolve_parent_candidate_id(request)
        try:
            candidate = await factory.create_error_driven_revision_candidate(
                tool_name=request.tool.name,
                error_type=analysis.error_type,
                error_message=error_text,
                user_id=str(request.execution_context.metadata.get("user_id") or "default"),
                source_session_id=str(
                    request.execution_context.metadata.get("session_id") or ""
                )
                or None,
                parent_candidate_id=parent_candidate_id,
                metadata={
                    "error_analysis": {
                        "error_type": analysis.error_type,
                        "context_for_fix": analysis.context_for_fix,
                        "suggested_fix_prompt": analysis.suggested_fix_prompt,
                    }
                },
            )
            rollout_status = "pending"
            if self.auto_grayscale:
                materialized = await factory.approve_and_materialize(
                    candidate.id,
                    approver="auto_revision_system",
                )
                materialized = await factory.transition_rollout_status(
                    candidate_id=materialized.id,
                    target_status=ArtifactRolloutStatus.GRAYSCALE,
                    operator="auto_revision_system",
                    reason="auto_error_revision_grayscale",
                    metadata={
                        "source": "auto_skill_revision",
                        "error_type": analysis.error_type,
                    },
                )
                candidate = materialized
                rollout_status = "grayscale"
            result.metadata["auto_revision_candidate_id"] = candidate.id
            result.metadata["auto_revision_triggered"] = True
            result.metadata["auto_revision_rollout_status"] = rollout_status
            notices = request.execution_context.metadata.setdefault("auto_revision_notifications", [])
            notices.append(
                {
                    "type": "auto_skill_revised",
                    "candidate_id": candidate.id,
                    "tool_name": request.tool.name,
                    "error_type": analysis.error_type,
                    "rollout_status": rollout_status,
                }
            )
            request.execution_context.metadata["auto_revision_notifications"] = notices[-20:]
        except Exception as exc:
            logger.warning(
                "Auto revision trigger failed for tool=%s call_id=%s: %s",
                request.tool.name,
                request.tool_call.id,
                exc,
            )
        return result

    def _is_failed_result(self, result: ToolResult) -> bool:
        if result.is_error:
            return True
        content = (result.content or "").strip()
        if not content:
            return False
        try:
            payload = json.loads(content)
            if isinstance(payload, dict) and payload.get("error"):
                return True
        except Exception:
            pass
        return False

    def _extract_error_text(self, result: ToolResult) -> str:
        if result.is_error:
            return result.content or ""
        content = (result.content or "").strip()
        try:
            payload = json.loads(content)
            if isinstance(payload, dict) and payload.get("error"):
                return str(payload.get("error"))
        except Exception:
            pass
        return content

    def _is_call_already_triggered(self, request: ToolExecutionRequest) -> bool:
        key = "auto_revision_triggered_calls"
        bucket = request.execution_context.metadata.setdefault(key, [])
        if request.tool_call.id in bucket:
            return True
        bucket.append(request.tool_call.id)
        request.execution_context.metadata[key] = bucket[-100:]
        return False

    def _consume_quota(self, request: ToolExecutionRequest) -> bool:
        key = "auto_revision_trigger_count"
        count = int(request.execution_context.metadata.get(key) or 0)
        if count >= self.max_per_execution:
            return False
        request.execution_context.metadata[key] = count + 1
        return True

    async def _resolve_parent_candidate_id(self, request: ToolExecutionRequest) -> Optional[str]:
        from ..artifacts import get_artifact_factory_service
        module_name = str(request.tool.metadata.get("module") or "")
        parts = module_name.split(".")
        # module_path follows "skills.{skill_id}.{entry}" for installed skills.
        skill_id = parts[1].strip() if len(parts) >= 3 and parts[0] == "skills" else ""
        if not skill_id:
            return None
        factory = get_artifact_factory_service()
        candidates = await factory.list_candidates()
        for item in candidates:
            if (
                item.status.value == "materialized"
                and str(item.materialized_ref_id or "").strip() == skill_id
            ):
                return item.id
        return None
