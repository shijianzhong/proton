import json
import hashlib
import logging
import re
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .assessor import AssessmentResult, ValueAssessor
from ..core.agent_node import AgentNode
from ..core.models import (
    AgentConfig,
    AgentType,
    ArtifactCandidate,
    ArtifactCandidateStatus,
    ArtifactRolloutStatus,
    ArtifactType,
    BuiltinAgentDefinition,
)
from ..orchestration.workflow import get_workflow_manager
from ..plugins.skill_manager import get_skill_manager
from ..storage import initialize_storage
from ..storage.persistence import StorageManager

logger = logging.getLogger(__name__)


class ArtifactFactoryService:
    def __init__(self):
        self._storage: Optional[StorageManager] = None
        self._assessor = ValueAssessor()

    async def _ensure_storage(self):
        if self._storage is None:
            self._storage = await initialize_storage()

    async def decide_and_create_candidate(
        self,
        *,
        user_id: str,
        task_summary: str,
        source_session_id: Optional[str] = None,
        parent_candidate_id: Optional[str] = None,
        repeat_count: int = 1,
        tool_call_count: int = 0,
        unique_tool_count: int = 0,
        parallel_branches: int = 0,
        requires_long_running: bool = False,
        has_manual_steps: bool = False,
        failure_rate: float = 0.0,
        high_risk: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactCandidate:
        await self._ensure_storage()
        storage = self._storage
        if storage is None:
            raise RuntimeError("storage unavailable")

        signals = {
            "repeat_count": repeat_count,
            "tool_call_count": tool_call_count,
            "unique_tool_count": unique_tool_count,
            "parallel_branches": parallel_branches,
            "requires_long_running": requires_long_running,
            "has_manual_steps": has_manual_steps,
            "failure_rate": failure_rate,
            "high_risk": high_risk,
            "avg_duration_sec": float((metadata or {}).get("avg_duration_sec") or 0.0),
            "user_explicit_save": bool((metadata or {}).get("user_explicit_save")),
            "strong_signal": bool((metadata or {}).get("strong_signal")),
            "precipitation_level": str((metadata or {}).get("precipitation_level") or ""),
        }
        decision = self._decide_type(
            repeat_count=repeat_count,
            tool_call_count=tool_call_count,
            unique_tool_count=unique_tool_count,
            parallel_branches=parallel_branches,
            requires_long_running=requires_long_running,
            has_manual_steps=has_manual_steps,
            failure_rate=failure_rate,
            high_risk=high_risk,
        )
        artifact_type = decision["artifact_type"]
        confidence = float(decision["confidence"])
        reasons = list(decision["reasons"])
        assessment = self._assessor.assess(task_summary=task_summary, signals=signals)
        if assessment.reasons:
            reasons.extend([f"assessor:{item}" for item in assessment.reasons[:4]])
        draft = self._build_draft(
            artifact_type=artifact_type,
            task_summary=task_summary,
        )
        if artifact_type == ArtifactType.SKILL and assessment.suggested_skill_name:
            draft["name"] = assessment.suggested_skill_name
        merged_metadata = dict(metadata or {})
        merged_metadata["value_assessment"] = assessment.to_dict()
        lineage_id = ""
        root_candidate_id = ""
        version = 1
        if parent_candidate_id:
            parent = await self.get_candidate(parent_candidate_id)
            if not parent:
                raise ValueError(f"parent candidate not found: {parent_candidate_id}")
            lineage_id = parent.lineage_id or parent.id
            root_candidate_id = (
                self._extract_root_candidate_id(parent) or parent_candidate_id
            )
            version = max(1, int(parent.version or 1) + 1)
        else:
            lineage_id = str(uuid4())
            root_candidate_id = ""

        self._append_decision_explanation(
            metadata=merged_metadata,
            source=str(merged_metadata.get("signal_source") or "manual"),
            task_summary=task_summary,
            signals=signals,
            decision=decision,
        )
        candidate = ArtifactCandidate(
            id=str(uuid4()),
            user_id=user_id,
            source_session_id=source_session_id,
            lineage_id=lineage_id,
            parent_candidate_id=parent_candidate_id,
            version=version,
            task_summary=task_summary,
            artifact_type=artifact_type,
            confidence=confidence,
            reasons=reasons,
            draft=draft,
            status=ArtifactCandidateStatus.PENDING,
            metadata=merged_metadata,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        if not root_candidate_id:
            root_candidate_id = candidate.id
        self._append_lineage_metadata(
            metadata=candidate.metadata,
            candidate_id=candidate.id,
            lineage_id=lineage_id,
            version=version,
            parent_candidate_id=parent_candidate_id,
            root_candidate_id=root_candidate_id,
        )
        await storage.save_artifact_candidate(candidate.model_dump())
        return candidate

    async def auto_create_controlled_candidates(
        self,
        *,
        candidate_ids: List[str],
        operator: str = "auto_system",
        dry_run: bool = False,
        limit: int = 5,
    ) -> Dict[str, Any]:
        await self._ensure_storage()
        storage = self._storage
        if storage is None:
            raise RuntimeError("storage unavailable")

        reviewed = 0
        auto_created = 0
        rows: List[Dict[str, Any]] = []
        for candidate_id in candidate_ids[: max(0, int(limit))]:
            candidate = await self.get_candidate(candidate_id)
            if not candidate:
                continue
            reviewed += 1
            if candidate.status != ArtifactCandidateStatus.PENDING:
                rows.append(
                    {
                        "candidate_id": candidate.id,
                        "eligible": False,
                        "reason": f"status={candidate.status.value}",
                    }
                )
                continue
            if candidate.artifact_type != ArtifactType.SKILL:
                rows.append(
                    {
                        "candidate_id": candidate.id,
                        "eligible": False,
                        "reason": f"artifact_type={candidate.artifact_type.value}",
                    }
                )
                continue

            assessment = self._build_candidate_assessment(candidate)
            candidate.metadata["value_assessment"] = assessment.to_dict()
            if not assessment.should_auto_create:
                candidate.updated_at = datetime.now()
                await storage.save_artifact_candidate(candidate.model_dump())
                rows.append(
                    {
                        "candidate_id": candidate.id,
                        "eligible": False,
                        "reason": "assessment_not_passed",
                        "assessment": assessment.to_dict(),
                    }
                )
                continue

            if dry_run:
                rows.append(
                    {
                        "candidate_id": candidate.id,
                        "eligible": True,
                        "would_auto_create": True,
                        "assessment": assessment.to_dict(),
                    }
                )
                continue

            materialized = await self.approve_and_materialize(
                candidate.id,
                approver=operator,
            )
            if materialized.status == ArtifactCandidateStatus.MATERIALIZED:
                auto_meta = {
                    "operator": operator,
                    "created_at": datetime.now().isoformat(),
                    "assessment": assessment.to_dict(),
                }
                materialized.metadata["creation_mode"] = "auto_controlled"
                materialized.metadata["rollout_guard"] = "grayscale_only"
                materialized.metadata["auto_create"] = auto_meta
                await storage.save_artifact_candidate(materialized.model_dump())
                materialized = await self.transition_rollout_status(
                    candidate_id=materialized.id,
                    target_status=ArtifactRolloutStatus.GRAYSCALE,
                    operator=operator,
                    reason="auto_controlled_create",
                    metadata={
                        "creation_mode": "auto_controlled",
                        "assessment_score": assessment.score,
                    },
                )
                materialized.metadata["creation_mode"] = "auto_controlled"
                materialized.metadata["rollout_guard"] = "grayscale_only"
                materialized.metadata["auto_create"] = auto_meta
                materialized.updated_at = datetime.now()
                await storage.save_artifact_candidate(materialized.model_dump())
                auto_created += 1
            rows.append(
                {
                    "candidate_id": candidate.id,
                    "eligible": True,
                    "auto_created": True,
                    "rollout_status": ArtifactRolloutStatus.GRAYSCALE.value,
                    "assessment": assessment.to_dict(),
                }
            )

        return {
            "reviewed_count": reviewed,
            "auto_created_count": auto_created,
            "items": rows,
        }

    async def create_error_driven_revision_candidate(
        self,
        *,
        tool_name: str,
        error_type: str,
        error_message: str,
        user_id: str = "default",
        source_session_id: Optional[str] = None,
        parent_candidate_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactCandidate:
        merged_metadata = dict(metadata or {})
        merged_metadata["signal_source"] = "tool_error_auto_revision"
        merged_metadata["error_revision_trigger"] = {
            "tool_name": tool_name,
            "error_type": error_type,
            "error_message": (error_message or "")[:500],
            "triggered_at": datetime.now().isoformat(),
        }
        summary = f"修复技能 {tool_name} 的 {error_type} 问题"
        return await self.decide_and_create_candidate(
            user_id=user_id,
            source_session_id=source_session_id,
            parent_candidate_id=parent_candidate_id,
            task_summary=summary,
            repeat_count=2,
            tool_call_count=2,
            unique_tool_count=1,
            parallel_branches=0,
            requires_long_running=False,
            has_manual_steps=False,
            failure_rate=0.2,
            high_risk=False,
            metadata=merged_metadata,
        )

    async def decide_from_execution_trajectory(
        self,
        *,
        user_id: str,
        source_session_id: str,
        messages: List[Dict[str, Any]],
        all_sessions_user_messages: Optional[List[str]] = None,
        tool_execution_audit: Optional[List[Dict[str, Any]]] = None,
        approval_results: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactCandidate:
        task_summary = self._extract_task_summary(messages)
        signals = self._extract_decision_signals(
            task_summary=task_summary,
            messages=messages,
            all_sessions_user_messages=all_sessions_user_messages or [],
            tool_execution_audit=tool_execution_audit or [],
            approval_results=approval_results or [],
        )
        merged_metadata = dict(metadata or {})
        merged_metadata["signal_source"] = "execution_trajectory"
        merged_metadata["trajectory"] = {
            "message_count": len(messages),
            "tool_call_count": signals["tool_call_count"],
            "unique_tool_count": signals["unique_tool_count"],
            "parallel_branches": signals["parallel_branches"],
            "approval_signal_count": signals["approval_signal_count"],
            "audit_entry_count": signals["audit_entry_count"],
        }

        return await self.decide_and_create_candidate(
            user_id=user_id,
            source_session_id=source_session_id,
            task_summary=task_summary,
            repeat_count=signals["repeat_count"],
            tool_call_count=signals["tool_call_count"],
            unique_tool_count=signals["unique_tool_count"],
            parallel_branches=signals["parallel_branches"],
            requires_long_running=signals["requires_long_running"],
            has_manual_steps=signals["has_manual_steps"],
            failure_rate=signals["failure_rate"],
            high_risk=signals["high_risk"],
            metadata=merged_metadata,
        )

    async def list_candidates(
        self,
        status: Optional[ArtifactCandidateStatus] = None,
        user_id: Optional[str] = None,
    ) -> List[ArtifactCandidate]:
        await self._ensure_storage()
        storage = self._storage
        if storage is None:
            raise RuntimeError("storage unavailable")
        rows = await storage.list_artifact_candidates()
        items: List[ArtifactCandidate] = []
        for row in rows:
            try:
                item = ArtifactCandidate(**row)
            except Exception:
                continue
            if status and item.status != status:
                continue
            if user_id and item.user_id != user_id:
                continue
            items.append(item)
        items.sort(key=lambda x: x.updated_at, reverse=True)
        return items

    async def get_candidate(self, candidate_id: str) -> Optional[ArtifactCandidate]:
        await self._ensure_storage()
        storage = self._storage
        if storage is None:
            raise RuntimeError("storage unavailable")
        row = await storage.load_artifact_candidate(candidate_id)
        if not row:
            return None
        return ArtifactCandidate(**row)

    async def approve_and_materialize(
        self,
        candidate_id: str,
        approver: str = "system",
        bind_agent_id: Optional[str] = None,
    ) -> ArtifactCandidate:
        await self._ensure_storage()
        storage = self._storage
        if storage is None:
            raise RuntimeError("storage unavailable")
        candidate = await self.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")

        if candidate.artifact_type == ArtifactType.NONE:
            candidate.status = ArtifactCandidateStatus.REJECTED
            candidate.approved_by = approver
            candidate.updated_at = datetime.now()
            await storage.save_artifact_candidate(candidate.model_dump())
            return candidate

        if candidate.artifact_type == ArtifactType.WORKFLOW:
            workflow_id = await self._materialize_workflow(candidate)
            candidate.materialized_ref_id = workflow_id
        elif candidate.artifact_type == ArtifactType.SKILL:
            skill_id = await self._materialize_skill(candidate, bind_agent_id=bind_agent_id)
            candidate.materialized_ref_id = skill_id

        candidate.status = ArtifactCandidateStatus.MATERIALIZED
        candidate.approved_by = approver
        candidate.rollout_status = ArtifactRolloutStatus.NOT_STARTED
        candidate.rollout_history.append(
            {
                "event": "materialized",
                "operator": approver,
                "status": candidate.rollout_status.value,
                "at": datetime.now().isoformat(),
            }
        )
        candidate.updated_at = datetime.now()
        await storage.save_artifact_candidate(candidate.model_dump())
        return candidate

    async def collect_effect_metrics(
        self,
        *,
        candidate_id: str,
        metrics: Dict[str, Any],
        reporter: str = "system",
    ) -> ArtifactCandidate:
        await self._ensure_storage()
        storage = self._storage
        if storage is None:
            raise RuntimeError("storage unavailable")
        candidate = await self.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")

        if candidate.status != ArtifactCandidateStatus.MATERIALIZED:
            raise ValueError("candidate is not materialized")

        metric_event = {
            "timestamp": datetime.now().isoformat(),
            "reporter": reporter,
            **metrics,
        }
        candidate.effect_metrics.append(metric_event)
        self._refresh_effect_metric_summary(candidate)
        metric_summary = self._compute_metric_summary(candidate.effect_metrics)
        self._evaluate_metric_alerts(
            candidate=candidate,
            latest_metric=metric_event,
            metric_summary=metric_summary,
        )
        candidate.updated_at = datetime.now()
        await storage.save_artifact_candidate(candidate.model_dump())
        return candidate

    async def decide_rollout_action(
        self,
        *,
        candidate_id: str,
        min_sample_size: int = 20,
        upgrade_success_rate: float = 0.97,
        rollback_error_rate: float = 0.08,
        max_latency_p95_ms: float = 2500.0,
        min_success_rate_for_rollback: float = 0.85,
        auto_apply: bool = False,
        operator: str = "system",
    ) -> Dict[str, Any]:
        candidate = await self.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")

        summary = self._compute_metric_summary(candidate.effect_metrics)
        decision = self._build_rollout_decision(
            summary=summary,
            rollout_status=candidate.rollout_status,
            min_sample_size=min_sample_size,
            upgrade_success_rate=upgrade_success_rate,
            rollback_error_rate=rollback_error_rate,
            max_latency_p95_ms=max_latency_p95_ms,
            min_success_rate_for_rollback=min_success_rate_for_rollback,
        )

        response = {
            "candidate_id": candidate.id,
            "current_rollout_status": candidate.rollout_status.value,
            "decision": decision["action"],
            "reason": decision["reason"],
            "recommended_target_status": decision["recommended_target_status"],
            "metric_summary": summary,
        }
        freeze_state = self._get_rollback_freeze_state(candidate)
        response["rollback_freeze"] = freeze_state
        if (
            freeze_state["active"]
            and candidate.rollout_status == ArtifactRolloutStatus.ROLLED_BACK
        ):
            response["decision"] = "hold"
            response["reason"] = (
                f"回滚冻结窗口生效中，冻结截止时间 {freeze_state.get('freeze_until')}"
            )
            response["recommended_target_status"] = None
        if auto_apply and response["recommended_target_status"]:
            updated = await self.transition_rollout_status(
                candidate_id=candidate_id,
                target_status=ArtifactRolloutStatus(response["recommended_target_status"]),
                operator=operator,
                reason=f"auto_decision:{response['decision']}",
            )
            response["applied"] = True
            response["updated_rollout_status"] = updated.rollout_status.value
        else:
            response["applied"] = False
        return response

    async def auto_manage_rollouts(
        self,
        *,
        user_id: Optional[str] = None,
        candidate_ids: Optional[List[str]] = None,
        only_rollout_status: ArtifactRolloutStatus = ArtifactRolloutStatus.GRAYSCALE,
        min_sample_size: int = 20,
        upgrade_success_rate: float = 0.97,
        rollback_error_rate: float = 0.08,
        max_latency_p95_ms: float = 2500.0,
        min_success_rate_for_rollback: float = 0.85,
        auto_apply: bool = True,
        dry_run: bool = False,
        operator: str = "rollout-bot",
        limit: int = 50,
    ) -> Dict[str, Any]:
        candidate_set = {str(item).strip() for item in (candidate_ids or []) if str(item).strip()}
        all_candidates = await self.list_candidates(user_id=user_id)
        selected: List[ArtifactCandidate] = []
        for item in all_candidates:
            if item.status != ArtifactCandidateStatus.MATERIALIZED:
                continue
            if item.rollout_status != only_rollout_status:
                continue
            if candidate_set and item.id not in candidate_set:
                continue
            selected.append(item)
        selected = selected[: max(1, min(limit, 500))]

        items: List[Dict[str, Any]] = []
        applied_count = 0
        decision_counter: Counter[str] = Counter()
        for candidate in selected:
            decision = await self.decide_rollout_action(
                candidate_id=candidate.id,
                min_sample_size=min_sample_size,
                upgrade_success_rate=upgrade_success_rate,
                rollback_error_rate=rollback_error_rate,
                max_latency_p95_ms=max_latency_p95_ms,
                min_success_rate_for_rollback=min_success_rate_for_rollback,
                auto_apply=(auto_apply and not dry_run),
                operator=operator,
            )
            decision_counter[str(decision.get("decision") or "unknown")] += 1
            if bool(decision.get("applied")):
                applied_count += 1
            items.append(decision)

        return {
            "scope": {
                "user_id": user_id,
                "candidate_ids": sorted(candidate_set) if candidate_set else [],
                "only_rollout_status": only_rollout_status.value,
            },
            "input": {
                "min_sample_size": min_sample_size,
                "upgrade_success_rate": upgrade_success_rate,
                "rollback_error_rate": rollback_error_rate,
                "max_latency_p95_ms": max_latency_p95_ms,
                "min_success_rate_for_rollback": min_success_rate_for_rollback,
                "auto_apply": auto_apply,
                "dry_run": dry_run,
                "operator": operator,
                "limit": limit,
            },
            "summary": {
                "selected_count": len(selected),
                "applied_count": applied_count,
                "decisions": dict(decision_counter),
            },
            "items": items,
        }

    async def transition_rollout_status(
        self,
        *,
        candidate_id: str,
        target_status: ArtifactRolloutStatus,
        operator: str = "system",
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        freeze_window_minutes: Optional[int] = None,
        manual_override: bool = False,
        override_reason: Optional[str] = None,
    ) -> ArtifactCandidate:
        await self._ensure_storage()
        storage = self._storage
        if storage is None:
            raise RuntimeError("storage unavailable")
        candidate = await self.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")

        if candidate.status != ArtifactCandidateStatus.MATERIALIZED:
            raise ValueError("candidate is not materialized")

        current = candidate.rollout_status
        freeze_state = self._get_rollback_freeze_state(candidate)
        if (
            freeze_state["active"]
            and current == ArtifactRolloutStatus.ROLLED_BACK
            and target_status != ArtifactRolloutStatus.ROLLED_BACK
            and not manual_override
        ):
            raise ValueError(
                f"rollback freeze window active until {freeze_state.get('freeze_until')}"
            )
        if current == target_status:
            return candidate
        if target_status not in self._allowed_rollout_transitions(current):
            raise ValueError(
                f"invalid rollout transition: {current.value} -> {target_status.value}"
            )

        now = datetime.now()
        transition_metadata = dict(metadata or {})
        if manual_override:
            transition_metadata["manual_override"] = True
            transition_metadata["override_reason"] = override_reason
            self._clear_rollback_freeze(
                candidate,
                operator=operator,
                reason=override_reason or reason or "manual_override",
            )
        candidate.rollout_status = target_status
        candidate.rollout_history.append(
            {
                "event": "rollout_transition",
                "from_status": current.value,
                "to_status": target_status.value,
                "operator": operator,
                "reason": reason,
                "metadata": transition_metadata,
                "at": now.isoformat(),
            }
        )
        self._append_alert_event(
            candidate,
            event_type="rollout_transition",
            severity="info",
            title="灰度状态变更",
            message=f"{current.value} -> {target_status.value}",
            payload={
                "from_status": current.value,
                "to_status": target_status.value,
                "operator": operator,
                "reason": reason,
                "metadata": transition_metadata,
            },
        )
        if target_status == ArtifactRolloutStatus.ROLLED_BACK:
            self._activate_rollback_freeze(
                candidate,
                operator=operator,
                reason=reason,
                freeze_window_minutes=freeze_window_minutes,
            )
        candidate.updated_at = now
        await storage.save_artifact_candidate(candidate.model_dump())
        return candidate

    async def get_candidate_lineage(self, candidate_id: str) -> Dict[str, Any]:
        candidate = await self.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")
        lineage_id = candidate.lineage_id or candidate.id
        candidates = await self.list_candidates()
        lineage_items = [item for item in candidates if (item.lineage_id or item.id) == lineage_id]
        lineage_items.sort(key=lambda x: (int(x.version or 1), x.created_at))
        return {
            "lineage_id": lineage_id,
            "candidate_id": candidate_id,
            "count": len(lineage_items),
            "items": [
                {
                    "id": item.id,
                    "version": int(item.version or 1),
                    "parent_candidate_id": item.parent_candidate_id,
                    "artifact_type": item.artifact_type.value,
                    "status": item.status.value,
                    "rollout_status": item.rollout_status.value,
                    "materialized_ref_id": item.materialized_ref_id,
                    "created_at": item.created_at.isoformat(),
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in lineage_items
            ],
        }

    async def configure_ab_routing(
        self,
        *,
        candidate_id: str,
        enabled: bool = True,
        control_ratio: float = 0.5,
        salt: str = "",
        operator: str = "system",
        notes: Optional[str] = None,
    ) -> ArtifactCandidate:
        await self._ensure_storage()
        storage = self._storage
        if storage is None:
            raise RuntimeError("storage unavailable")
        candidate = await self.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")
        if control_ratio < 0 or control_ratio > 1:
            raise ValueError("control_ratio must be between 0 and 1")
        now = datetime.now()
        metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        candidate.metadata = metadata
        cfg = metadata.setdefault("ab_routing", {})
        if not isinstance(cfg, dict):
            cfg = {}
            metadata["ab_routing"] = cfg
        cfg.update(
            {
                "enabled": bool(enabled),
                "control_ratio": round(float(control_ratio), 6),
                "treatment_ratio": round(1.0 - float(control_ratio), 6),
                "salt": salt,
                "updated_by": operator,
                "notes": notes or "",
                "updated_at": now.isoformat(),
            }
        )
        candidate.updated_at = now
        await storage.save_artifact_candidate(candidate.model_dump())
        return candidate

    async def route_candidate_ab_bucket(
        self,
        *,
        candidate_id: str,
        subject_key: str,
        force_bucket: Optional[str] = None,
        force_target_candidate_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        candidate = await self.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")
        if not subject_key:
            raise ValueError("subject_key is required")

        metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        cfg = metadata.get("ab_routing") if isinstance(metadata, dict) else None
        cfg = cfg if isinstance(cfg, dict) else {}
        enabled = bool(cfg.get("enabled", candidate.rollout_status == ArtifactRolloutStatus.GRAYSCALE))
        control_ratio = self._safe_float(cfg.get("control_ratio"))
        if control_ratio is None:
            control_ratio = 0.5
        control_ratio = max(0.0, min(1.0, control_ratio))
        salt = str(cfg.get("salt", ""))

        hash_input = f"{candidate.id}:{salt}:{subject_key}"
        bucket_value = int(hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
        bucket = "control" if bucket_value < control_ratio else "treatment"
        if not enabled:
            bucket = "treatment"
        if force_bucket in {"control", "treatment"}:
            bucket = force_bucket

        target_candidate_id = candidate.id
        if bucket == "control" and candidate.parent_candidate_id:
            target_candidate_id = candidate.parent_candidate_id
        if force_target_candidate_id:
            target_candidate_id = force_target_candidate_id

        return {
            "candidate_id": candidate.id,
            "subject_key": subject_key,
            "bucket": bucket,
            "target_candidate_id": target_candidate_id,
            "ab_routing": {
                "enabled": enabled,
                "control_ratio": control_ratio,
                "salt": salt,
                "hash_value": round(bucket_value, 8),
                "forced": bool(force_bucket or force_target_candidate_id),
            },
        }

    async def get_rollback_freeze(self, candidate_id: str) -> Dict[str, Any]:
        candidate = await self.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")
        return {
            "candidate_id": candidate.id,
            "rollout_status": candidate.rollout_status.value,
            **self._get_rollback_freeze_state(candidate),
        }

    async def override_rollback_freeze(
        self,
        *,
        candidate_id: str,
        operator: str = "system",
        reason: str = "manual_override",
    ) -> ArtifactCandidate:
        await self._ensure_storage()
        storage = self._storage
        if storage is None:
            raise RuntimeError("storage unavailable")
        candidate = await self.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")
        self._clear_rollback_freeze(candidate, operator=operator, reason=reason)
        candidate.updated_at = datetime.now()
        await storage.save_artifact_candidate(candidate.model_dump())
        return candidate

    async def get_decision_explanations(self, candidate_id: str) -> List[Dict[str, Any]]:
        candidate = await self.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {candidate_id}")
        metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        explanations = metadata.get("decision_explanations") or []
        if not isinstance(explanations, list):
            return []
        return explanations

    async def get_metrics_dashboard(
        self,
        *,
        user_id: Optional[str] = None,
        include_candidates: int = 20,
    ) -> Dict[str, Any]:
        candidates = await self.list_candidates(user_id=user_id)
        type_counter = Counter(c.artifact_type.value for c in candidates)
        status_counter = Counter(c.status.value for c in candidates)
        rollout_counter = Counter(c.rollout_status.value for c in candidates)

        metric_summaries: List[Dict[str, Any]] = []
        snapshots: List[Dict[str, Any]] = []
        alerts: List[Dict[str, Any]] = []
        for candidate in candidates:
            summary = self._compute_metric_summary(candidate.effect_metrics)
            metric_summaries.append(summary)
            events = self._get_candidate_alert_events(candidate)
            for event in events:
                row = dict(event)
                row["candidate_id"] = candidate.id
                row["user_id"] = candidate.user_id
                alerts.append(row)
            snapshots.append(
                {
                    "candidate_id": candidate.id,
                    "task_summary": candidate.task_summary,
                    "artifact_type": candidate.artifact_type.value,
                    "status": candidate.status.value,
                    "rollout_status": candidate.rollout_status.value,
                    "confidence": candidate.confidence,
                    "sample_size": summary.get("sample_size") or 0,
                    "metric_summary": summary,
                    "latest_alert": events[-1] if events else None,
                    "updated_at": candidate.updated_at.isoformat(),
                }
            )

        alert_counter = Counter(
            str(event.get("severity", "info")).lower() for event in alerts
        )
        alerts.sort(
            key=lambda x: str(x.get("timestamp", "")),
            reverse=True,
        )

        snapshots = snapshots[: max(1, include_candidates)]

        return {
            "generated_at": datetime.now().isoformat(),
            "scope": {"user_id": user_id},
            "overview": {
                "total_candidates": len(candidates),
                "by_artifact_type": dict(type_counter),
                "by_status": dict(status_counter),
                "by_rollout_status": dict(rollout_counter),
                "materialized_count": status_counter.get(
                    ArtifactCandidateStatus.MATERIALIZED.value, 0
                ),
            },
            "metrics": self._aggregate_metric_summaries(metric_summaries),
            "alerts": {
                "total": len(alerts),
                "by_severity": dict(alert_counter),
                "latest_events": alerts[:20],
            },
            "candidate_snapshots": snapshots,
        }

    async def list_alert_events(
        self,
        *,
        user_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        candidates = await self.list_candidates(user_id=user_id)
        severity_filter = str(severity).lower().strip() if severity else ""
        items: List[Dict[str, Any]] = []
        for candidate in candidates:
            if candidate_id and candidate.id != candidate_id:
                continue
            for event in self._get_candidate_alert_events(candidate):
                row = dict(event)
                row["candidate_id"] = candidate.id
                row["user_id"] = candidate.user_id
                if severity_filter and str(row.get("severity", "")).lower() != severity_filter:
                    continue
                items.append(row)
        items.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)
        return items[: max(1, min(limit, 500))]

    async def discover_candidates_by_trajectory_clustering(
        self,
        *,
        trajectories: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        min_cluster_size: int = 2,
        similarity_threshold: float = 0.6,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Cluster execution trajectories and discover reusable candidate opportunities.

        Week4 capability:
        - Group similar trajectories by task signature
        - Aggregate signals per cluster
        - Auto-create candidates for high-confidence repeated clusters
        """
        threshold = max(0.1, min(1.0, float(similarity_threshold)))
        min_cluster_size = max(1, int(min_cluster_size))
        clusters: List[Dict[str, Any]] = []
        analyzed = 0

        for trajectory in trajectories:
            if not isinstance(trajectory, dict):
                continue
            messages = trajectory.get("messages") or []
            if not isinstance(messages, list):
                continue
            task_summary = self._extract_task_summary(messages)
            token_set = self._token_set(task_summary)
            if not token_set:
                continue
            analyzed += 1
            best_idx = -1
            best_score = 0.0
            for idx, cluster in enumerate(clusters):
                score = self._token_jaccard(
                    token_set,
                    set(cluster.get("token_set") or []),
                )
                if score > best_score:
                    best_score = score
                    best_idx = idx
            if best_idx >= 0 and best_score >= threshold:
                target = clusters[best_idx]
                target["members"].append(trajectory)
                target["task_summaries"].append(task_summary)
                target["token_set"] = sorted(set(target["token_set"]) | token_set)
            else:
                clusters.append(
                    {
                        "members": [trajectory],
                        "task_summaries": [task_summary],
                        "token_set": sorted(token_set),
                    }
                )

        eligible_clusters = [c for c in clusters if len(c["members"]) >= min_cluster_size]
        created_candidates: List[ArtifactCandidate] = []
        candidate_rows: List[Dict[str, Any]] = []
        existing = await self.list_candidates(user_id=user_id)

        for cluster in eligible_clusters:
            aggregated = self._aggregate_cluster_signals(cluster["members"])
            summary = self._pick_cluster_summary(cluster["task_summaries"])
            signature = self._build_cluster_signature(cluster["token_set"])
            owner = user_id or aggregated.get("major_user_id") or "default"
            existing_candidate = self._find_existing_cluster_candidate(
                candidates=existing,
                user_id=owner,
                cluster_signature=signature,
            )
            if existing_candidate:
                candidate_rows.append(
                    {
                        "cluster_signature": signature,
                        "task_summary": summary,
                        "candidate_id": existing_candidate.id,
                        "created": False,
                        "reason": "existing_candidate",
                    }
                )
                continue

            cluster_meta = {
                "signal_source": "trajectory_cluster",
                "trajectory_cluster": {
                    "signature": signature,
                    "cluster_size": len(cluster["members"]),
                    "token_set": cluster["token_set"],
                    "session_ids": [
                        str(item.get("session_id", ""))
                        for item in cluster["members"]
                        if str(item.get("session_id", "")).strip()
                    ],
                },
            }
            if dry_run:
                candidate_rows.append(
                    {
                        "cluster_signature": signature,
                        "task_summary": summary,
                        "candidate_id": None,
                        "created": False,
                        "reason": "dry_run",
                        "signals": aggregated,
                    }
                )
                continue

            created = await self.decide_and_create_candidate(
                user_id=owner,
                source_session_id=aggregated.get("major_session_id"),
                task_summary=summary,
                repeat_count=max(int(aggregated.get("repeat_count", 1)), min_cluster_size),
                tool_call_count=int(aggregated.get("tool_call_count", 0)),
                unique_tool_count=int(aggregated.get("unique_tool_count", 0)),
                parallel_branches=int(aggregated.get("parallel_branches", 0)),
                requires_long_running=bool(aggregated.get("requires_long_running", False)),
                has_manual_steps=bool(aggregated.get("has_manual_steps", False)),
                failure_rate=float(aggregated.get("failure_rate", 0.0)),
                high_risk=bool(aggregated.get("high_risk", False)),
                metadata=cluster_meta,
            )
            created_candidates.append(created)
            existing.append(created)
            candidate_rows.append(
                {
                    "cluster_signature": signature,
                    "task_summary": summary,
                    "candidate_id": created.id,
                    "created": True,
                    "artifact_type": created.artifact_type.value,
                }
            )

        return {
            "analyzed_trajectories": analyzed,
            "cluster_count": len(clusters),
            "eligible_cluster_count": len(eligible_clusters),
            "created_count": len(created_candidates),
            "items": candidate_rows,
            "created_candidates": [c.model_dump() for c in created_candidates],
        }

    async def auto_trigger_revisions(
        self,
        *,
        user_id: Optional[str] = None,
        min_sample_size: int = 12,
        success_rate_threshold: float = 0.85,
        error_rate_threshold: float = 0.12,
        quality_score_threshold: float = 0.75,
        latency_p95_threshold_ms: float = 3500.0,
        cooldown_hours: int = 24,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Automatically trigger revision candidates for degraded materialized artifacts.

        Week4 capability:
        - Monitor metric drift/regression
        - Create revision candidate automatically with parent linkage
        """
        min_sample_size = max(1, int(min_sample_size))
        cooldown_hours = max(0, int(cooldown_hours))
        now = datetime.now()
        all_candidates = await self.list_candidates(user_id=user_id)
        materialized = [
            c for c in all_candidates if c.status == ArtifactCandidateStatus.MATERIALIZED
        ]
        triggered_rows: List[Dict[str, Any]] = []
        created_rows: List[Dict[str, Any]] = []

        for candidate in materialized:
            summary = self._compute_metric_summary(candidate.effect_metrics)
            sample_size = int(summary.get("sample_size") or 0)
            if sample_size < min_sample_size:
                continue

            avg_success = self._safe_float(summary.get("avg_success_rate"))
            avg_error = self._safe_float(summary.get("avg_error_rate"))
            avg_quality = self._safe_float(summary.get("avg_quality_score"))
            avg_latency = self._safe_float(summary.get("avg_latency_p95_ms"))
            degradation_reasons: List[str] = []
            if avg_success is not None and avg_success < success_rate_threshold:
                degradation_reasons.append(
                    f"success_rate<{success_rate_threshold:.2f}"
                )
            if avg_error is not None and avg_error > error_rate_threshold:
                degradation_reasons.append(
                    f"error_rate>{error_rate_threshold:.2f}"
                )
            if avg_quality is not None and avg_quality < quality_score_threshold:
                degradation_reasons.append(
                    f"quality_score<{quality_score_threshold:.2f}"
                )
            if avg_latency is not None and avg_latency > latency_p95_threshold_ms:
                degradation_reasons.append(
                    f"latency_p95>{latency_p95_threshold_ms:.0f}ms"
                )
            if not degradation_reasons:
                continue

            child_candidates = [
                item
                for item in all_candidates
                if item.parent_candidate_id == candidate.id
                and item.status != ArtifactCandidateStatus.REJECTED
            ]
            if child_candidates and cooldown_hours > 0:
                latest_child = max(child_candidates, key=lambda x: x.created_at)
                age_seconds = (now - latest_child.created_at).total_seconds()
                if age_seconds < cooldown_hours * 3600:
                    triggered_rows.append(
                        {
                            "candidate_id": candidate.id,
                            "triggered": False,
                            "reason": "cooldown_active",
                            "latest_child_candidate_id": latest_child.id,
                            "latest_child_status": latest_child.status.value,
                            "degradation_reasons": degradation_reasons,
                        }
                    )
                    continue

            revision_summary = f"{candidate.task_summary}（自动修订）"
            signal_hint = self._revision_signal_hint(candidate, summary)
            revision_metadata = {
                "signal_source": "auto_revision_trigger",
                "revision_trigger": {
                    "from_candidate_id": candidate.id,
                    "degradation_reasons": degradation_reasons,
                    "metric_summary": summary,
                    "triggered_at": now.isoformat(),
                    "cooldown_hours": cooldown_hours,
                },
            }
            triggered_rows.append(
                {
                    "candidate_id": candidate.id,
                    "triggered": True,
                    "degradation_reasons": degradation_reasons,
                    "signals": signal_hint,
                }
            )
            if dry_run:
                continue

            created = await self.decide_and_create_candidate(
                user_id=candidate.user_id,
                source_session_id=candidate.source_session_id,
                parent_candidate_id=candidate.id,
                task_summary=revision_summary,
                repeat_count=signal_hint["repeat_count"],
                tool_call_count=signal_hint["tool_call_count"],
                unique_tool_count=signal_hint["unique_tool_count"],
                parallel_branches=signal_hint["parallel_branches"],
                requires_long_running=signal_hint["requires_long_running"],
                has_manual_steps=signal_hint["has_manual_steps"],
                failure_rate=signal_hint["failure_rate"],
                high_risk=False,
                metadata=revision_metadata,
            )
            all_candidates.append(created)
            created_rows.append(
                {
                    "from_candidate_id": candidate.id,
                    "revision_candidate_id": created.id,
                    "artifact_type": created.artifact_type.value,
                }
            )

        return {
            "scanned_count": len(materialized),
            "triggered_count": len([x for x in triggered_rows if x.get("triggered")]),
            "created_count": len(created_rows),
            "items": triggered_rows,
            "created_items": created_rows,
        }

    async def run_periodic_learning_cycle(
        self,
        *,
        trajectories: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        min_cluster_size: int = 2,
        dry_run: bool = False,
        trigger_revision: bool = True,
        min_revision_samples: int = 12,
        revision_cooldown_hours: int = 24,
        trigger_auto_create: bool = False,
        auto_create_limit: int = 5,
    ) -> Dict[str, Any]:
        """
        Run a full periodic learning cycle:
        1) trajectory clustering discovery
        2) auto revision triggering
        """
        discovery = await self.discover_candidates_by_trajectory_clustering(
            trajectories=trajectories,
            user_id=user_id,
            min_cluster_size=min_cluster_size,
            dry_run=dry_run,
        )
        revision = {
            "scanned_count": 0,
            "triggered_count": 0,
            "created_count": 0,
            "items": [],
            "created_items": [],
        }
        if trigger_revision:
            revision = await self.auto_trigger_revisions(
                user_id=user_id,
                min_sample_size=min_revision_samples,
                cooldown_hours=revision_cooldown_hours,
                dry_run=dry_run,
            )
        auto_creation = {
            "reviewed_count": 0,
            "auto_created_count": 0,
            "items": [],
        }
        if trigger_auto_create:
            created_ids = [
                str(item.get("id"))
                for item in discovery.get("created_candidates", [])
                if isinstance(item, dict) and item.get("id")
            ]
            auto_creation = await self.auto_create_controlled_candidates(
                candidate_ids=created_ids,
                operator="auto_system",
                dry_run=dry_run,
                limit=auto_create_limit,
            )
        return {
            "generated_at": datetime.now().isoformat(),
            "scope": {"user_id": user_id},
            "dry_run": dry_run,
            "trajectory_clustering": discovery,
            "auto_revision": revision,
            "auto_controlled_creation": auto_creation,
            "summary": {
                "discovered_candidates": discovery.get("created_count", 0),
                "triggered_revisions": revision.get("created_count", 0),
                "auto_created_skills": auto_creation.get("auto_created_count", 0),
            },
        }

    async def export_trajectories_as_sharegpt(
        self,
        *,
        trajectories: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        portal_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        from_time: Optional[str] = None,
        to_time: Optional[str] = None,
        min_quality_score: float = 0.0,
        limit: int = 500,
    ) -> Dict[str, Any]:
        from_dt = self._parse_iso_dt(from_time)
        to_dt = self._parse_iso_dt(to_time)
        if from_dt and to_dt and from_dt > to_dt:
            raise ValueError("from_time must be <= to_time")

        normalized_limit = max(1, min(limit, 5000))
        items: List[Dict[str, Any]] = []
        skipped_quality = 0
        scanned = 0

        for tr in trajectories:
            scanned += 1
            sid = str(tr.get("session_id") or "").strip()
            if not sid:
                continue
            tr_user_id = str(tr.get("user_id") or "").strip()
            if user_id and tr_user_id != user_id:
                continue

            metadata = tr.get("metadata") if isinstance(tr.get("metadata"), dict) else {}
            tr_portal_id = str((metadata or {}).get("portal_id") or "").strip()
            if portal_id and tr_portal_id != portal_id:
                continue

            tr_workflow_id = str(tr.get("workflow_id") or "").strip()
            if not tr_workflow_id:
                tr_workflow_id = str((metadata or {}).get("workflow_id") or "").strip()
            if workflow_id and tr_workflow_id != workflow_id:
                continue

            updated_at = self._parse_iso_dt(str(tr.get("updated_at") or ""))
            if from_dt and (not updated_at or updated_at < from_dt):
                continue
            if to_dt and (not updated_at or updated_at > to_dt):
                continue

            raw_messages = tr.get("messages")
            messages_for_export = raw_messages if isinstance(raw_messages, list) else []
            conversations = self._to_sharegpt_conversations(messages=messages_for_export)
            if len(conversations) < 2:
                continue
            quality = self._compute_sharegpt_quality(conversations)
            if quality < min_quality_score:
                skipped_quality += 1
                continue
            items.append(
                {
                    "id": sid,
                    "conversations": conversations,
                    "quality_score": round(quality, 6),
                    "meta": {
                        "session_id": sid,
                        "user_id": tr_user_id or "default",
                        "portal_id": tr_portal_id or None,
                        "workflow_id": tr_workflow_id or None,
                        "updated_at": str(tr.get("updated_at") or ""),
                    },
                }
            )
            if len(items) >= normalized_limit:
                break

        return {
            "generated_at": datetime.now().isoformat(),
            "format": "sharegpt",
            "count": len(items),
            "items": items,
            "filters": {
                "user_id": user_id,
                "portal_id": portal_id,
                "workflow_id": workflow_id,
                "from_time": from_time,
                "to_time": to_time,
                "min_quality_score": min_quality_score,
                "limit": normalized_limit,
            },
            "stats": {
                "scanned_sessions": scanned,
                "skipped_by_quality": skipped_quality,
            },
        }

    async def recommend_skill_transfers(
        self,
        *,
        target_portal_id: str,
        user_id: Optional[str] = None,
        top_k: int = 10,
        min_score: float = 0.15,
        include_pending: bool = True,
    ) -> Dict[str, Any]:
        from ..portal import get_portal_manager

        portal_mgr = get_portal_manager()
        target_portal = await portal_mgr.get_portal(target_portal_id)
        if not target_portal:
            raise ValueError(f"target portal not found: {target_portal_id}")

        candidates = await self.list_candidates(user_id=user_id)
        allowed_status = {ArtifactCandidateStatus.MATERIALIZED}
        if include_pending:
            allowed_status.add(ArtifactCandidateStatus.PENDING)
        rows: List[Dict[str, Any]] = []
        target_text = f"{target_portal.name}\n{target_portal.description}".strip()
        for item in candidates:
            if item.artifact_type != ArtifactType.SKILL:
                continue
            if item.status not in allowed_status:
                continue
            source_portal_id = str(item.metadata.get("source_portal_id") or "").strip()
            if source_portal_id and source_portal_id == target_portal_id:
                continue
            cand_text = self._build_transfer_candidate_text(item)
            semantic = self._token_similarity(target_text, cand_text)
            raw_assessment = item.metadata.get("value_assessment")
            raw_score = raw_assessment.get("score") if isinstance(raw_assessment, dict) else None
            value_score = self._safe_float(raw_score) or 0.0
            rollout_bonus = 0.0
            if item.status == ArtifactCandidateStatus.MATERIALIZED:
                rollout_bonus += 0.12
            if item.rollout_status in {
                ArtifactRolloutStatus.GRAYSCALE,
                ArtifactRolloutStatus.FULL_RELEASED,
            }:
                rollout_bonus += 0.08
            score = max(0.0, min(1.0, round(0.65 * semantic + 0.25 * value_score + rollout_bonus, 6)))
            if score < min_score:
                continue
            rows.append(
                {
                    "candidate_id": item.id,
                    "materialized_skill_id": item.materialized_ref_id,
                    "task_summary": item.task_summary,
                    "source_portal_id": source_portal_id or None,
                    "status": item.status.value,
                    "rollout_status": item.rollout_status.value,
                    "score": score,
                    "score_breakdown": {
                        "semantic": round(semantic, 6),
                        "value_score": round(value_score, 6),
                        "rollout_bonus": round(rollout_bonus, 6),
                    },
                    "recommendation": "review_then_bind_to_target_portal",
                }
            )

        rows.sort(key=lambda x: x["score"], reverse=True)
        result_items = rows[: max(1, min(top_k, 100))]
        return {
            "target_portal": {
                "id": target_portal.id,
                "name": target_portal.name,
                "description": target_portal.description,
            },
            "count": len(result_items),
            "items": result_items,
            "filters": {
                "user_id": user_id,
                "top_k": top_k,
                "min_score": min_score,
                "include_pending": include_pending,
            },
        }

    def _build_candidate_assessment(self, candidate: ArtifactCandidate) -> AssessmentResult:
        metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        traj = metadata.get("trajectory_cluster") if isinstance(metadata, dict) else {}
        traj = traj if isinstance(traj, dict) else {}
        explanations = metadata.get("decision_explanations") if isinstance(metadata, dict) else []
        signals: Dict[str, Any] = {}
        if isinstance(explanations, list) and explanations:
            last = explanations[-1]
            if isinstance(last, dict) and isinstance(last.get("signals"), dict):
                signals.update(last["signals"])
        signals.setdefault("repeat_count", int(traj.get("cluster_size") or 1))
        signals.setdefault("failure_rate", self._safe_float(metadata.get("failure_rate")) or 0.0)
        signals.setdefault("tool_call_count", self._safe_int(signals.get("tool_call_count"), 0))
        signals.setdefault("avg_duration_sec", self._safe_float(metadata.get("avg_duration_sec")) or 0.0)
        signals.setdefault("strong_signal", bool(metadata.get("strong_signal")))
        signals.setdefault("precipitation_level", str(metadata.get("precipitation_level") or ""))
        return self._assessor.assess(task_summary=candidate.task_summary, signals=signals)

    @staticmethod
    def _parse_iso_dt(raw: Optional[str]) -> Optional[datetime]:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    @staticmethod
    def _to_sharegpt_conversations(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        role_map = {
            "user": "human",
            "assistant": "gpt",
            "system": "system",
            "tool": "tool",
        }
        out: List[Dict[str, str]] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip().lower()
            value = str(msg.get("content") or "").strip()
            if not role or not value:
                continue
            out.append({"from": role_map.get(role, role), "value": value})
        return out

    @staticmethod
    def _compute_sharegpt_quality(conversations: List[Dict[str, str]]) -> float:
        if not conversations:
            return 0.0
        user_turns = 0
        assistant_turns = 0
        total_chars = 0
        for item in conversations:
            who = str(item.get("from") or "")
            val = str(item.get("value") or "")
            total_chars += len(val)
            if who == "human":
                user_turns += 1
            elif who == "gpt":
                assistant_turns += 1
        if user_turns == 0 or assistant_turns == 0:
            return 0.0
        turn_score = min(1.0, (user_turns + assistant_turns) / 6.0)
        length_score = min(1.0, total_chars / 1600.0)
        balance = 1.0 - min(1.0, abs(user_turns - assistant_turns) / max(1, user_turns + assistant_turns))
        return max(0.0, min(1.0, 0.4 * turn_score + 0.4 * length_score + 0.2 * balance))

    @staticmethod
    def _build_transfer_candidate_text(candidate: ArtifactCandidate) -> str:
        pieces: List[str] = [candidate.task_summary]
        if candidate.reasons:
            pieces.extend(candidate.reasons[:3])
        if isinstance(candidate.metadata, dict):
            explain = candidate.metadata.get("decision_explanations")
            if isinstance(explain, list) and explain:
                first = explain[0]
                if isinstance(first, dict):
                    pieces.append(str(first.get("task_summary") or ""))
        return "\n".join([p for p in pieces if str(p).strip()])

    @staticmethod
    def _token_similarity(a: str, b: str) -> float:
        ta = ArtifactFactoryService._tokenize(a)
        tb = ArtifactFactoryService._tokenize(b)
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        union = len(ta | tb)
        if union <= 0:
            return 0.0
        return inter / union

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        import re

        parts = re.findall(r"[a-z0-9\u4e00-\u9fff]+", (text or "").lower())
        return {p for p in parts if p}

    def _decide_type(
        self,
        *,
        repeat_count: int,
        tool_call_count: int,
        unique_tool_count: int,
        parallel_branches: int,
        requires_long_running: bool,
        has_manual_steps: bool,
        failure_rate: float,
        high_risk: bool,
    ) -> Dict[str, Any]:
        reasons: List[str] = []
        if high_risk and repeat_count < 3:
            reasons.append("高风险且复用证据不足，暂不建议自动生成")
            return {
                "artifact_type": ArtifactType.NONE,
                "confidence": 0.25,
                "reasons": reasons,
                "scores": {"workflow_score": 0, "skill_score": 0},
                "risk_blocked": True,
            }

        workflow_score = 0
        skill_score = 0

        if parallel_branches > 1:
            workflow_score += 3
            reasons.append("存在并行分支，偏向生成 workflow")
        if requires_long_running:
            workflow_score += 2
            reasons.append("任务存在长期运行需求，偏向 workflow 编排")
        if has_manual_steps:
            workflow_score += 1
            reasons.append("包含人工步骤，适合 workflow 治理")
        if tool_call_count >= 4:
            workflow_score += 1

        if repeat_count >= 2:
            skill_score += 3
            reasons.append("任务重复出现，具备技能沉淀价值")
        if unique_tool_count <= 2:
            skill_score += 1
        if tool_call_count <= 3:
            skill_score += 1
        if failure_rate <= 0.2:
            skill_score += 1

        if workflow_score >= skill_score and workflow_score >= 2:
            confidence = min(0.95, 0.55 + workflow_score * 0.08)
            return {
                "artifact_type": ArtifactType.WORKFLOW,
                "confidence": confidence,
                "reasons": reasons,
                "scores": {
                    "workflow_score": workflow_score,
                    "skill_score": skill_score,
                },
                "risk_blocked": False,
            }
        if skill_score > workflow_score and skill_score >= 2:
            confidence = min(0.95, 0.55 + skill_score * 0.08)
            return {
                "artifact_type": ArtifactType.SKILL,
                "confidence": confidence,
                "reasons": reasons,
                "scores": {
                    "workflow_score": workflow_score,
                    "skill_score": skill_score,
                },
                "risk_blocked": False,
            }
        reasons.append("当前信号不足，建议继续观察后再生成")
        return {
            "artifact_type": ArtifactType.NONE,
            "confidence": 0.4,
            "reasons": reasons,
            "scores": {"workflow_score": workflow_score, "skill_score": skill_score},
            "risk_blocked": False,
        }

    def _build_draft(self, *, artifact_type: ArtifactType, task_summary: str) -> Dict[str, Any]:
        normalized = self._safe_name(task_summary)
        if artifact_type == ArtifactType.SKILL:
            return {
                "name": f"{normalized}_skill",
                "description": task_summary,
                "function_name": "execute",
                "parameters_schema": {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string", "description": "用户输入"},
                    },
                    "required": ["input"],
                },
            }
        if artifact_type == ArtifactType.WORKFLOW:
            return {
                "name": f"{normalized}_workflow",
                "description": task_summary,
                "root_agent": {
                    "name": "Coordinator",
                    "description": task_summary,
                    "system_prompt": f"你负责执行并协调任务：{task_summary}",
                },
            }
        return {"description": task_summary}

    def _extract_task_summary(self, messages: List[Dict[str, Any]]) -> str:
        user_contents = [
            str(msg.get("content", "")).strip()
            for msg in messages
            if str(msg.get("role", "")).lower() == "user" and str(msg.get("content", "")).strip()
        ]
        if user_contents:
            return user_contents[-1][:200]
        for msg in reversed(messages):
            content = str(msg.get("content", "")).strip()
            if content:
                return content[:200]
        return "自动提取任务"

    def _extract_decision_signals(
        self,
        *,
        task_summary: str,
        messages: List[Dict[str, Any]],
        all_sessions_user_messages: List[str],
        tool_execution_audit: List[Dict[str, Any]],
        approval_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        tool_calls: List[Dict[str, Any]] = []
        max_parallel = 0
        error_count = 0
        result_count = 0
        text_fragments: List[str] = [task_summary]
        user_messages = []

        for msg in messages:
            role = str(msg.get("role", "")).lower()
            content = str(msg.get("content", "")).strip()
            if content:
                text_fragments.append(content)
            if role == "user" and content:
                user_messages.append(content)
            raw_calls = msg.get("tool_calls") or []
            if isinstance(raw_calls, list):
                max_parallel = max(max_parallel, len(raw_calls))
                for call in raw_calls:
                    if isinstance(call, dict):
                        tool_calls.append(call)
            raw_results = msg.get("tool_results") or []
            if isinstance(raw_results, list):
                for result in raw_results:
                    if not isinstance(result, dict):
                        continue
                    result_count += 1
                    status = str(result.get("status", "")).lower()
                    error = result.get("error")
                    if status in {"error", "failed"} or error:
                        error_count += 1

        audit_calls, audit_parallel, audit_error_count, audit_result_count = (
            self._extract_audit_signals(tool_execution_audit)
        )
        if audit_calls:
            tool_calls.extend(audit_calls)
        max_parallel = max(max_parallel, audit_parallel)
        error_count += audit_error_count
        result_count += audit_result_count

        normalized_all = [
            self._normalize_text_for_repeat(v)
            for v in all_sessions_user_messages
            if self._normalize_text_for_repeat(v)
        ]
        normalized_current = self._normalize_text_for_repeat(task_summary)
        repeat_count = 1
        if normalized_current and normalized_all:
            repeat_count = max(
                1,
                sum(1 for item in normalized_all if item == normalized_current),
            )
        elif user_messages:
            local_counter = Counter(self._normalize_text_for_repeat(v) for v in user_messages)
            repeat_count = max(1, local_counter.most_common(1)[0][1]) if local_counter else 1

        tool_names = [
            str(tc.get("name", "")).strip()
            for tc in tool_calls
            if isinstance(tc, dict) and str(tc.get("name", "")).strip()
        ]
        unique_tool_count = len(set(tool_names))
        tool_call_count = len(tool_calls)

        combined_text = " ".join(text_fragments).lower()
        approval_signal_count, has_manual_step_from_approval = self._extract_approval_signals(
            approval_results
        )
        has_audit_manual_steps = any(
            str(item.get("status", "")).lower() in {"blocked", "denied"}
            for item in tool_execution_audit
            if isinstance(item, dict)
        )
        has_audit_high_risk = any(
            bool(item.get("is_dangerous"))
            for item in tool_execution_audit
            if isinstance(item, dict)
        )
        requires_long_running = self._contains_any(
            combined_text,
            ["长期运行", "持续", "监控", "实时", "定时", "watch", "daemon"],
        )
        has_manual_steps = has_manual_step_from_approval or has_audit_manual_steps or self._contains_any(
            combined_text,
            ["人工", "手动", "审批", "review", "confirm", "approval"],
        )
        high_risk = has_audit_high_risk or self._contains_any(
            combined_text,
            ["删除", "转账", "支付", "生产环境", "高危", "rm -rf", "危险"],
        )
        failure_rate = (error_count / result_count) if result_count > 0 else 0.0

        return {
            "repeat_count": repeat_count,
            "tool_call_count": tool_call_count,
            "unique_tool_count": unique_tool_count,
            "parallel_branches": max_parallel,
            "requires_long_running": requires_long_running,
            "has_manual_steps": has_manual_steps,
            "failure_rate": failure_rate,
            "high_risk": high_risk,
            "approval_signal_count": approval_signal_count,
            "audit_entry_count": len(tool_execution_audit),
        }

    def _aggregate_cluster_signals(
        self,
        trajectories: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not trajectories:
            return {
                "repeat_count": 1,
                "tool_call_count": 0,
                "unique_tool_count": 0,
                "parallel_branches": 0,
                "requires_long_running": False,
                "has_manual_steps": False,
                "failure_rate": 0.0,
                "high_risk": False,
                "major_session_id": None,
                "major_user_id": None,
            }
        aggregated: List[Dict[str, Any]] = []
        session_counter: Counter[str] = Counter()
        user_counter: Counter[str] = Counter()
        for item in trajectories:
            messages = item.get("messages") or []
            if not isinstance(messages, list):
                continue
            signals = self._extract_decision_signals(
                task_summary=self._extract_task_summary(messages),
                messages=messages,
                all_sessions_user_messages=[],
                tool_execution_audit=item.get("tool_execution_audit") or [],
                approval_results=item.get("approval_results") or [],
            )
            aggregated.append(signals)
            session_id = str(item.get("session_id", "")).strip()
            if session_id:
                session_counter[session_id] += 1
            uid = str(item.get("user_id", "")).strip()
            if uid:
                user_counter[uid] += 1
        if not aggregated:
            return {
                "repeat_count": len(trajectories),
                "tool_call_count": 0,
                "unique_tool_count": 0,
                "parallel_branches": 0,
                "requires_long_running": False,
                "has_manual_steps": False,
                "failure_rate": 0.0,
                "high_risk": False,
                "major_session_id": None,
                "major_user_id": None,
            }
        count = len(aggregated)
        return {
            "repeat_count": len(trajectories),
            "tool_call_count": int(
                round(sum(int(x.get("tool_call_count", 0)) for x in aggregated) / count)
            ),
            "unique_tool_count": int(
                round(
                    sum(int(x.get("unique_tool_count", 0)) for x in aggregated) / count
                )
            ),
            "parallel_branches": max(int(x.get("parallel_branches", 0)) for x in aggregated),
            "requires_long_running": any(
                bool(x.get("requires_long_running", False)) for x in aggregated
            ),
            "has_manual_steps": any(bool(x.get("has_manual_steps", False)) for x in aggregated),
            "failure_rate": round(
                sum(float(x.get("failure_rate", 0.0)) for x in aggregated) / count,
                6,
            ),
            "high_risk": any(bool(x.get("high_risk", False)) for x in aggregated),
            "major_session_id": (
                session_counter.most_common(1)[0][0] if session_counter else None
            ),
            "major_user_id": user_counter.most_common(1)[0][0] if user_counter else None,
        }

    def _pick_cluster_summary(self, summaries: List[str]) -> str:
        clean = [str(x).strip() for x in summaries if str(x).strip()]
        if not clean:
            return "自动聚类发现任务"
        normalized = [self._normalize_text_for_repeat(x) for x in clean]
        cnt = Counter(normalized)
        target_norm = cnt.most_common(1)[0][0]
        for item, norm in zip(clean, normalized):
            if norm == target_norm:
                return item[:200]
        return clean[0][:200]

    def _build_cluster_signature(self, token_items: List[str]) -> str:
        ordered = sorted(set(token_items))
        digest = hashlib.sha1("|".join(ordered).encode("utf-8")).hexdigest()
        return f"cluster_{digest[:16]}"

    def _find_existing_cluster_candidate(
        self,
        *,
        candidates: List[ArtifactCandidate],
        user_id: str,
        cluster_signature: str,
    ) -> Optional[ArtifactCandidate]:
        for candidate in candidates:
            if candidate.user_id != user_id:
                continue
            if candidate.status == ArtifactCandidateStatus.REJECTED:
                continue
            metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
            cluster = metadata.get("trajectory_cluster") if isinstance(metadata, dict) else None
            if not isinstance(cluster, dict):
                continue
            if str(cluster.get("signature", "")) == cluster_signature:
                return candidate
        return None

    def _revision_signal_hint(
        self,
        candidate: ArtifactCandidate,
        summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        trajectory = metadata.get("trajectory") if isinstance(metadata, dict) else {}
        trajectory = trajectory if isinstance(trajectory, dict) else {}
        sample_size = int(summary.get("sample_size") or 0)
        avg_error = self._safe_float(summary.get("avg_error_rate")) or 0.0
        is_workflow = candidate.artifact_type == ArtifactType.WORKFLOW
        return {
            "repeat_count": max(2, min(8, sample_size // 4 or 2)),
            "tool_call_count": max(
                2,
                self._safe_int(trajectory.get("tool_call_count"), 2),
            ),
            "unique_tool_count": max(
                1,
                self._safe_int(trajectory.get("unique_tool_count"), 1),
            ),
            "parallel_branches": (
                max(2, self._safe_int(trajectory.get("parallel_branches"), 2))
                if is_workflow
                else self._safe_int(trajectory.get("parallel_branches"), 1)
            ),
            "requires_long_running": is_workflow
            or bool(trajectory.get("requires_long_running", False)),
            "has_manual_steps": bool(trajectory.get("has_manual_steps", False)),
            "failure_rate": max(0.0, min(1.0, avg_error)),
        }

    @staticmethod
    def _token_set(text: str) -> set[str]:
        lowered = str(text or "").lower()
        tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", lowered)
        return set(tokens)

    @staticmethod
    def _token_jaccard(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        inter = left & right
        union = left | right
        if not union:
            return 0.0
        return len(inter) / len(union)

    def _extract_audit_signals(
        self,
        tool_execution_audit: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], int, int, int]:
        tool_calls: List[Dict[str, Any]] = []
        error_count = 0
        result_count = 0
        for item in tool_execution_audit:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool_name", "")).strip()
            if tool_name:
                tool_calls.append(
                    {
                        "id": item.get("tool_call_id") or "",
                        "name": tool_name,
                    }
                )
            result_count += 1
            status = str(item.get("status", "")).lower()
            if status in {"error", "denied"} or bool(item.get("is_error")):
                error_count += 1
        max_parallel = len(tool_calls)
        return tool_calls, max_parallel, error_count, result_count

    def _extract_approval_signals(self, approval_results: List[Dict[str, Any]]) -> tuple[int, bool]:
        signal_count = 0
        has_manual_steps = False
        for item in approval_results:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "")).lower()
            if status in {"pending", "approved", "denied"}:
                signal_count += 1
                has_manual_steps = True
        return signal_count, has_manual_steps

    async def _materialize_workflow(self, candidate: ArtifactCandidate) -> str:
        manager = get_workflow_manager()
        name = candidate.draft.get("name") or "auto_generated_workflow"
        description = candidate.task_summary
        root_cfg = candidate.draft.get("root_agent", {})
        root_agent = AgentNode(
            name=root_cfg.get("name", "Coordinator"),
            description=root_cfg.get("description", description),
            type=AgentType.BUILTIN,
            config=AgentConfig(
                builtin_definition=BuiltinAgentDefinition(
                    name=root_cfg.get("name", "Coordinator"),
                    description=root_cfg.get("description", description),
                    system_prompt=root_cfg.get(
                        "system_prompt",
                        f"你负责执行任务：{description}",
                    ),
                )
            ),
        )
        workflow = await manager.create_workflow(
            name=name,
            description=description,
            root_agent=root_agent,
        )
        await manager.save_current_state(workflow.id)
        return workflow.id

    async def _generate_skill_code_via_llm(self, candidate: ArtifactCandidate) -> Optional[str]:
        try:
            import os
            from openai import AsyncOpenAI
            from ..copilot import get_copilot_service
            
            copilot = get_copilot_service()
            copilot_cfg = copilot.get_config()
            api_key = copilot_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY")
            base_url = copilot_cfg.get("base_url")
            model = copilot_cfg.get("model", "gpt-4")
            
            kwargs = {}
            if api_key:
                kwargs["api_key"] = api_key
            else:
                kwargs["api_key"] = "placeholder"
            if base_url:
                kwargs["base_url"] = base_url
                
            client = AsyncOpenAI(**kwargs)
            
            prompt = f"""
You are an expert Python developer. Generate a complete Python script for a skill.
The skill is named '{candidate.draft.get("name")}' and its description is '{candidate.task_summary}'.
The entry function must be named '{candidate.draft.get("function_name", "execute")}'.
It must accept the parameters defined in this JSON schema:
{json.dumps(candidate.draft.get("parameters_schema", {}), ensure_ascii=False)}

Requirements:
- The script should be self-contained.
- Do not use markdown blocks (```python) in your output, just return the raw Python code.
- Return a dictionary with results.
- Implement the logic to actually perform the task described. If it requires external APIs, write robust request logic. If it is a mock, make it a high-quality mock.
"""
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2048,
            )
            content = resp.choices[0].message.content
            code = (content or "").strip()
            if code.startswith("```python"):
                code = code[9:]
            elif code.startswith("```"):
                code = code[3:]
            if code.endswith("```"):
                code = code[:-3]
            return code.strip()
        except Exception as e:
            logger.error(f"Failed to generate skill code via LLM: {e}")
            return None

    async def _materialize_skill(
        self,
        candidate: ArtifactCandidate,
        *,
        bind_agent_id: Optional[str] = None,
    ) -> str:
        skill_manager = get_skill_manager()
        base_dir = Path("data/skills/generated")
        base_dir.mkdir(parents=True, exist_ok=True)
        package_dir = base_dir / candidate.id
        package_dir.mkdir(parents=True, exist_ok=True)

        skill_name = candidate.draft.get("name", f"skill_{candidate.id[:8]}")
        function_name = candidate.draft.get("function_name", "execute")
        parameters_schema = candidate.draft.get("parameters_schema", {})
        skill_desc = candidate.draft.get("description", candidate.task_summary)

        skill_md = (
            "---\n"
            f"name: {skill_name}\n"
            f"description: {skill_desc}\n"
            "version: 1.0.0\n"
            "author: proton-artifact-factory\n"
            "tags: [auto-generated, candidate]\n"
            "entry_point: skill.py\n"
            f"function_name: {function_name}\n"
            f"parameters_schema: {json.dumps(parameters_schema, ensure_ascii=False)}\n"
            "approval_required: false\n"
            "---\n"
        )
        (package_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

        # Use LLM to generate the actual skill code
        generated_code = await self._generate_skill_code_via_llm(candidate)

        if generated_code:
            # Verify generated code in sandbox before saving
            try:
                from ..execution.backends.local import LocalProcessBackend
                backend = LocalProcessBackend()
                # Quick syntax check with timeout
                test_code = f"import ast\nast.parse({repr(generated_code)})"
                result = await backend.run_python(test_code, {}, timeout=5)
                if result.error:
                    logger.warning(f"Generated code syntax check failed: {result.error}, using fallback")
                    generated_code = None
            except Exception as e:
                logger.warning(f"Code verification failed: {e}, using fallback")
                generated_code = None

        if generated_code:
            skill_py = generated_code
        else:
            skill_py = (
                "from typing import Any, Dict\n\n"
                f"def {function_name}(input: str, **kwargs: Any) -> Dict[str, Any]:\n"
                "    return {\n"
                f"        \"summary\": \"{skill_desc}\",\n"
                "        \"input\": input,\n"
                "        \"extra\": kwargs,\n"
                "    }\n"
            )
            
        (package_dir / "skill.py").write_text(skill_py, encoding="utf-8")

        archive_path = base_dir / f"{candidate.id}.skill"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(package_dir / "SKILL.md", arcname="SKILL.md")
            zf.write(package_dir / "skill.py", arcname="skill.py")

        installed = await skill_manager.install_skill(str(archive_path))
        if bind_agent_id:
            await skill_manager.bind_skill_to_agent(installed.id, bind_agent_id)
        return installed.id

    @staticmethod
    def _safe_name(text: str) -> str:
        tokens = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())
        short = "_".join(tokens[:6]) if tokens else "generated"
        return short[:60]

    @staticmethod
    def _normalize_text_for_repeat(text: str) -> str:
        tokens = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())
        return "".join(tokens)

    @staticmethod
    def _contains_any(text: str, keywords: List[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_iso_datetime(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None

    @staticmethod
    def _extract_root_candidate_id(candidate: ArtifactCandidate) -> Optional[str]:
        metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        lineage = metadata.get("lineage") if isinstance(metadata, dict) else None
        if isinstance(lineage, dict):
            root_id = lineage.get("root_candidate_id")
            if isinstance(root_id, str) and root_id:
                return root_id
        return None

    def _append_lineage_metadata(
        self,
        *,
        metadata: Dict[str, Any],
        candidate_id: str,
        lineage_id: str,
        version: int,
        parent_candidate_id: Optional[str],
        root_candidate_id: str,
    ) -> None:
        lineage = metadata.setdefault("lineage", {})
        if not isinstance(lineage, dict):
            lineage = {}
            metadata["lineage"] = lineage
        lineage["lineage_id"] = lineage_id
        lineage["candidate_id"] = candidate_id
        lineage["version"] = int(version)
        lineage["parent_candidate_id"] = parent_candidate_id
        lineage["root_candidate_id"] = root_candidate_id
        lineage["updated_at"] = datetime.now().isoformat()

    def _get_rollback_freeze_state(self, candidate: ArtifactCandidate) -> Dict[str, Any]:
        metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        cfg = metadata.get("rollback_freeze") if isinstance(metadata, dict) else None
        cfg = cfg if isinstance(cfg, dict) else {}
        freeze_until = self._parse_iso_datetime(cfg.get("freeze_until"))
        active = bool(cfg.get("active"))
        if active and freeze_until and datetime.now() >= freeze_until:
            active = False
        return {
            "active": active,
            "freeze_until": freeze_until.isoformat() if freeze_until else None,
            "frozen_by": cfg.get("frozen_by"),
            "reason": cfg.get("reason"),
            "override_by": cfg.get("override_by"),
            "override_reason": cfg.get("override_reason"),
            "override_at": cfg.get("override_at"),
            "window_minutes": self._safe_int(cfg.get("window_minutes"), 0),
        }

    def _activate_rollback_freeze(
        self,
        candidate: ArtifactCandidate,
        *,
        operator: str,
        reason: Optional[str],
        freeze_window_minutes: Optional[int],
    ) -> None:
        metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        candidate.metadata = metadata
        cfg = metadata.setdefault("rollback_freeze", {})
        if not isinstance(cfg, dict):
            cfg = {}
            metadata["rollback_freeze"] = cfg
        window_minutes = (
            freeze_window_minutes
            if freeze_window_minutes is not None
            else self._safe_int(cfg.get("default_window_minutes"), 60)
        )
        window_minutes = max(1, int(window_minutes))
        freeze_until = datetime.now() + timedelta(minutes=window_minutes)
        cfg.update(
            {
                "active": True,
                "window_minutes": window_minutes,
                "freeze_until": freeze_until.isoformat(),
                "frozen_by": operator,
                "reason": reason or "rollback",
                "updated_at": datetime.now().isoformat(),
            }
        )

    def _clear_rollback_freeze(
        self,
        candidate: ArtifactCandidate,
        *,
        operator: str,
        reason: str,
    ) -> None:
        metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        candidate.metadata = metadata
        cfg = metadata.setdefault("rollback_freeze", {})
        if not isinstance(cfg, dict):
            cfg = {}
            metadata["rollback_freeze"] = cfg
        cfg["active"] = False
        cfg["override_by"] = operator
        cfg["override_reason"] = reason
        cfg["override_at"] = datetime.now().isoformat()

    def _refresh_effect_metric_summary(self, candidate: ArtifactCandidate) -> None:
        summary = self._compute_metric_summary(candidate.effect_metrics)
        candidate.metadata.setdefault("effect_metrics", {})
        candidate.metadata["effect_metrics"]["summary"] = summary
        candidate.metadata["effect_metrics"]["sample_size"] = len(candidate.effect_metrics)
        candidate.metadata["effect_metrics"]["last_reported_at"] = datetime.now().isoformat()

    def _append_decision_explanation(
        self,
        *,
        metadata: Dict[str, Any],
        source: str,
        task_summary: str,
        signals: Dict[str, Any],
        decision: Dict[str, Any],
    ) -> None:
        explanations = metadata.setdefault("decision_explanations", [])
        if not isinstance(explanations, list):
            explanations = []
            metadata["decision_explanations"] = explanations
        artifact_type_value = decision.get("artifact_type")
        if isinstance(artifact_type_value, ArtifactType):
            artifact_type_text = artifact_type_value.value
        else:
            artifact_type_text = str(artifact_type_value or "")
        explanations.append(
            {
                "id": str(uuid4()),
                "timestamp": datetime.now().isoformat(),
                "source": source or "manual",
                "task_summary": task_summary,
                "signals": signals,
                "decision": {
                    "artifact_type": artifact_type_text,
                    "confidence": decision.get("confidence"),
                    "reasons": decision.get("reasons", []),
                    "scores": decision.get("scores", {}),
                    "risk_blocked": bool(decision.get("risk_blocked", False)),
                },
            }
        )

    def _get_candidate_alert_events(self, candidate: ArtifactCandidate) -> List[Dict[str, Any]]:
        metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        events = metadata.get("alert_events") or []
        return events if isinstance(events, list) else []

    def _append_alert_event(
        self,
        candidate: ArtifactCandidate,
        *,
        event_type: str,
        severity: str,
        title: str,
        message: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        candidate.metadata = metadata
        events = metadata.setdefault("alert_events", [])
        if not isinstance(events, list):
            events = []
            metadata["alert_events"] = events
        events.append(
            {
                "id": str(uuid4()),
                "timestamp": datetime.now().isoformat(),
                "event_type": event_type,
                "severity": severity,
                "title": title,
                "message": message,
                "payload": payload or {},
            }
        )

    def _evaluate_metric_alerts(
        self,
        *,
        candidate: ArtifactCandidate,
        latest_metric: Dict[str, Any],
        metric_summary: Dict[str, Any],
    ) -> None:
        metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
        candidate.metadata = metadata
        threshold_cfg = metadata.get("alert_thresholds") if isinstance(metadata, dict) else None
        threshold_cfg = threshold_cfg if isinstance(threshold_cfg, dict) else {}
        error_rate_critical = self._safe_float(threshold_cfg.get("error_rate_critical"))
        success_rate_warning = self._safe_float(threshold_cfg.get("success_rate_warning"))
        latency_warning_ms = self._safe_float(threshold_cfg.get("latency_p95_warning_ms"))
        quality_warning = self._safe_float(threshold_cfg.get("quality_score_warning"))

        if error_rate_critical is None:
            error_rate_critical = 0.12
        if success_rate_warning is None:
            success_rate_warning = 0.9
        if latency_warning_ms is None:
            latency_warning_ms = 3000.0
        if quality_warning is None:
            quality_warning = 0.75

        avg_error_rate = self._safe_float(metric_summary.get("avg_error_rate"))
        avg_success_rate = self._safe_float(metric_summary.get("avg_success_rate"))
        avg_latency = self._safe_float(metric_summary.get("avg_latency_p95_ms"))
        avg_quality = self._safe_float(metric_summary.get("avg_quality_score"))

        if avg_error_rate is not None and avg_error_rate >= error_rate_critical:
            self._append_alert_event(
                candidate,
                event_type="metric_threshold",
                severity="critical",
                title="错误率告警",
                message=f"平均错误率 {avg_error_rate:.4f} 超过阈值 {error_rate_critical:.4f}",
                payload={"metric_summary": metric_summary, "latest_metric": latest_metric},
            )
        if avg_success_rate is not None and avg_success_rate <= success_rate_warning:
            self._append_alert_event(
                candidate,
                event_type="metric_threshold",
                severity="warning",
                title="成功率告警",
                message=f"平均成功率 {avg_success_rate:.4f} 低于阈值 {success_rate_warning:.4f}",
                payload={"metric_summary": metric_summary, "latest_metric": latest_metric},
            )
        if avg_latency is not None and avg_latency >= latency_warning_ms:
            self._append_alert_event(
                candidate,
                event_type="metric_threshold",
                severity="warning",
                title="时延告警",
                message=f"平均 P95 时延 {avg_latency:.2f}ms 超过阈值 {latency_warning_ms:.2f}ms",
                payload={"metric_summary": metric_summary, "latest_metric": latest_metric},
            )
        if avg_quality is not None and avg_quality <= quality_warning:
            self._append_alert_event(
                candidate,
                event_type="metric_threshold",
                severity="warning",
                title="质量分告警",
                message=f"平均质量分 {avg_quality:.4f} 低于阈值 {quality_warning:.4f}",
                payload={"metric_summary": metric_summary, "latest_metric": latest_metric},
            )

    def _compute_metric_summary(self, metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not metrics:
            return {
                "sample_size": 0,
                "avg_success_rate": None,
                "avg_error_rate": None,
                "avg_latency_p95_ms": None,
                "avg_quality_score": None,
            }

        success_values: List[float] = []
        error_values: List[float] = []
        latency_values: List[float] = []
        quality_values: List[float] = []
        for item in metrics:
            if not isinstance(item, dict):
                continue
            success = self._safe_float(item.get("success_rate"))
            error = self._safe_float(item.get("error_rate"))
            latency = self._safe_float(item.get("latency_p95_ms"))
            quality = self._safe_float(item.get("quality_score"))
            if success is not None:
                success_values.append(success)
            if error is not None:
                error_values.append(error)
            if latency is not None:
                latency_values.append(latency)
            if quality is not None:
                quality_values.append(quality)

        def _avg(values: List[float]) -> Optional[float]:
            if not values:
                return None
            return round(sum(values) / len(values), 6)

        return {
            "sample_size": len(metrics),
            "avg_success_rate": _avg(success_values),
            "avg_error_rate": _avg(error_values),
            "avg_latency_p95_ms": _avg(latency_values),
            "avg_quality_score": _avg(quality_values),
        }

    def _aggregate_metric_summaries(self, summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not summaries:
            return {
                "tracked_candidates": 0,
                "total_samples": 0,
                "avg_success_rate": None,
                "avg_error_rate": None,
                "avg_latency_p95_ms": None,
                "avg_quality_score": None,
            }

        def _pick(key: str) -> List[float]:
            values: List[float] = []
            for item in summaries:
                value = self._safe_float(item.get(key))
                if value is not None:
                    values.append(value)
            return values

        def _avg(values: List[float]) -> Optional[float]:
            if not values:
                return None
            return round(sum(values) / len(values), 6)

        return {
            "tracked_candidates": len(summaries),
            "total_samples": sum(int(item.get("sample_size") or 0) for item in summaries),
            "avg_success_rate": _avg(_pick("avg_success_rate")),
            "avg_error_rate": _avg(_pick("avg_error_rate")),
            "avg_latency_p95_ms": _avg(_pick("avg_latency_p95_ms")),
            "avg_quality_score": _avg(_pick("avg_quality_score")),
        }

    def _build_rollout_decision(
        self,
        *,
        summary: Dict[str, Any],
        rollout_status: ArtifactRolloutStatus,
        min_sample_size: int,
        upgrade_success_rate: float,
        rollback_error_rate: float,
        max_latency_p95_ms: float,
        min_success_rate_for_rollback: float,
    ) -> Dict[str, Optional[str]]:
        sample_size = int(summary.get("sample_size") or 0)
        avg_success_rate = self._safe_float(summary.get("avg_success_rate"))
        avg_error_rate = self._safe_float(summary.get("avg_error_rate"))
        avg_latency = self._safe_float(summary.get("avg_latency_p95_ms"))
        if sample_size < min_sample_size:
            return {
                "action": "hold",
                "reason": f"样本不足（{sample_size}<{min_sample_size}），保持当前灰度状态",
                "recommended_target_status": None,
            }

        if (
            avg_error_rate is not None
            and avg_error_rate >= rollback_error_rate
        ) or (
            avg_success_rate is not None
            and avg_success_rate <= min_success_rate_for_rollback
        ):
            if rollout_status != ArtifactRolloutStatus.ROLLED_BACK:
                return {
                    "action": "rollback",
                    "reason": "错误率或成功率触发回滚阈值",
                    "recommended_target_status": ArtifactRolloutStatus.ROLLED_BACK.value,
                }
            return {
                "action": "hold",
                "reason": "已处于回滚状态，继续观察",
                "recommended_target_status": None,
            }

        can_upgrade = (
            avg_success_rate is not None
            and avg_success_rate >= upgrade_success_rate
            and (avg_error_rate is None or avg_error_rate < rollback_error_rate)
            and (avg_latency is None or avg_latency <= max_latency_p95_ms)
        )
        if can_upgrade and rollout_status in {
            ArtifactRolloutStatus.GRAYSCALE,
            ArtifactRolloutStatus.PAUSED,
        }:
            return {
                "action": "upgrade",
                "reason": "关键指标达到升级阈值，建议全量发布",
                "recommended_target_status": ArtifactRolloutStatus.FULL_RELEASED.value,
            }

        return {
            "action": "hold",
            "reason": "指标未触发升级或回滚条件，保持当前状态",
            "recommended_target_status": None,
        }

    @staticmethod
    def _allowed_rollout_transitions(
        status: ArtifactRolloutStatus,
    ) -> set[ArtifactRolloutStatus]:
        return {
            ArtifactRolloutStatus.NOT_STARTED: {
                ArtifactRolloutStatus.GRAYSCALE,
                ArtifactRolloutStatus.PAUSED,
                ArtifactRolloutStatus.ROLLED_BACK,
            },
            ArtifactRolloutStatus.GRAYSCALE: {
                ArtifactRolloutStatus.PAUSED,
                ArtifactRolloutStatus.FULL_RELEASED,
                ArtifactRolloutStatus.ROLLED_BACK,
            },
            ArtifactRolloutStatus.PAUSED: {
                ArtifactRolloutStatus.GRAYSCALE,
                ArtifactRolloutStatus.ROLLED_BACK,
            },
            ArtifactRolloutStatus.FULL_RELEASED: {
                ArtifactRolloutStatus.ROLLED_BACK,
            },
            ArtifactRolloutStatus.ROLLED_BACK: {
                ArtifactRolloutStatus.GRAYSCALE,
            },
        }.get(status, set())


_artifact_factory_service: Optional[ArtifactFactoryService] = None


def get_artifact_factory_service() -> ArtifactFactoryService:
    global _artifact_factory_service
    if _artifact_factory_service is None:
        _artifact_factory_service = ArtifactFactoryService()
    return _artifact_factory_service
