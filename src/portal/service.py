"""
Portal Service — Core runtime for the Super Portal.

Lifecycle of a single user turn:
  1. Load/create session  (PortalSession)
  2. Retrieve relevant memories
  3. Call IntentUnderstandingService → WorkflowDispatchPlan list
  4. Execute workflows (parallel where priority matches, sequential otherwise)
  5. Synthesise results into a final answer via LLM
  6. Extract & store new memories from the conversation turn
  7. Persist session
  8. Stream PortalEvents back to caller
"""

import asyncio
import json
import logging
import os
import secrets
import re
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Set
from uuid import uuid4

from ..execution.backends.local import LocalProcessBackend
from ..core.context import ContextOffloader, ExecutionContext
from ..core.models import (
    ChatMessage,
    ExecutionEventType,
    IntentUnderstandingResult,
    PortalConversationMessage,
    PortalEvent,
    PortalEventType,
    PortalMemoryEntry,
    PortalSession,
    SafetyScanResult,
    SuperPortalConfig,
    WorkflowDispatchPlan,
)
from ..orchestration.workflow import WorkflowManager, get_workflow_manager
from ..storage.persistence import StorageManager, get_storage_manager
from .intent import IntentUnderstandingService
from .memory_behavior import MemoryBehaviorEngine
from .mempalace_client import MemPalaceClient
from .mempalace_memory_provider import MemPalaceMemoryProvider
from .safety import PreGenerationSafetyScanner
from .trajectory import TrajectoryPool, has_strong_signal

logger = logging.getLogger(__name__)

PORTAL_COLLECTION = "portals"
SESSION_COLLECTION = "portal_sessions"
PENDING_EVENTS_KEY = "pending_portal_events"
SAFETY_BLOCK_MESSAGE = "当前请求触发安全策略，已在生成前拦截。请移除潜在注入/敏感指令后重试。"
NO_WORKFLOW_FALLBACK_DISABLED_MESSAGE = (
    "当前入口未配置可用工作流，且已关闭 fallback_to_copilot。"
    "请先绑定/发布工作流，或开启 fallback_to_copilot 后重试。"
)
NO_MATCH_FALLBACK_DISABLED_MESSAGE = (
    "未匹配到合适工作流，且已关闭 fallback_to_copilot。"
    "请补充更明确的需求，或开启 fallback_to_copilot 后重试。"
)

SYNTHESIS_SYSTEM_PROMPT = """You are a helpful assistant that synthesises results from multiple specialised workflows into a single, coherent, and well-formatted response.

Instructions:
- Integrate the workflow results naturally — do not just list them.
- Resolve any contradictions across workflows using good judgement.
- Be concise but complete.
- Use Markdown formatting where appropriate.
- Address the user directly.
"""

# Default backbone system prompt for Root Portal
DEFAULT_BACKBONE_SYSTEM_PROMPT = (
    "You are a helpful AI assistant. Answer the user's question directly, "
    "clearly, and concisely. Use Markdown formatting where appropriate."
)

# Singleton trajectory pool (shared across all portal services)
_global_trajectory_pool: Optional[TrajectoryPool] = None


def get_trajectory_pool() -> TrajectoryPool:
    global _global_trajectory_pool
    if _global_trajectory_pool is None:
        _global_trajectory_pool = TrajectoryPool()
    return _global_trajectory_pool


class PortalContextOffloader(ContextOffloader):
    def __init__(self, provider: MemPalaceMemoryProvider, portal_id: str, user_id: str):
        self.provider = provider
        self.portal_id = portal_id
        self.user_id = user_id
        self.semaphore = asyncio.Semaphore(3)

    async def offload(self, messages: List[ChatMessage], wing: str, room: str) -> Optional[Dict[str, Any]]:
        async with self.semaphore:
            content = "\n".join(f"[{m.role.value}] {m.content}" for m in messages)
            drawer_id = await self.provider.write_archive(
                portal_id=self.portal_id,
                user_id=self.user_id,
                wing=wing,
                room=room,
                content=content,
            )
            if drawer_id:
                return {
                    "wing": wing,
                    "room": room,
                    "drawer_id": drawer_id,
                    "count": len(messages),
                }
            return None


class PortalService:
    """
    Runtime service for a single Super Portal instance.

    One PortalService manages one SuperPortalConfig (identified by portal_id).
    Multiple portals can run in the same process via PortalManager.
    """

    def __init__(
        self,
        config: SuperPortalConfig,
        workflow_manager: WorkflowManager,
        storage: StorageManager,
        portal_manager: Optional["PortalManager"] = None,
    ):
        self.config = config
        self._wf_manager = workflow_manager
        self._storage = storage
        self._portal_manager = portal_manager
        
        client = MemPalaceClient(
            palace_path=getattr(config, "mempalace_palace_path", None),
            command=getattr(config, "mempalace_command", "mempalace"),
            args=getattr(config, "mempalace_args", None),
            env=getattr(config, "mempalace_env", None),
        )
        if str(getattr(config, "memory_provider", "mempalace")).strip().lower() not in ("mempalace", "mp"):
            logger.warning(
                "[Portal] memory_provider=%s is deprecated; forcing MemPalaceMemoryProvider",
                getattr(config, "memory_provider", None),
            )
        self.memory_provider = MemPalaceMemoryProvider(
            client=client,
            wing_strategy=getattr(config, "mempalace_wing_strategy", "per_user"),
            default_room=getattr(config, "mempalace_default_room", "general"),
        )
        self._safety_scanner = PreGenerationSafetyScanner()
        self._local_backend = LocalProcessBackend(
            workspace_dir=getattr(config, "workspace_dir", None),
            namespace=config.id
        )
        self._client = None   # lazy-initialised OpenAI client
        self._intent_svc: Optional[IntentUnderstandingService] = None
        self._memory_behavior = MemoryBehaviorEngine()
        self._memory_behavior_suggest_enabled = (
            str(os.environ.get("PORTAL_MEMORY_BEHAVIOR_SUGGEST_ENABLED", "true")).strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self._trajectory_auto_create_enabled = (
            str(os.environ.get("PORTAL_TRAJECTORY_AUTO_CREATE_ENABLED", "false")).strip().lower()
            in {"1", "true", "yes", "on"}
        )
        try:
            self._trajectory_auto_create_limit = max(
                1,
                int(str(os.environ.get("PORTAL_TRAJECTORY_AUTO_CREATE_LIMIT", "3")).strip()),
            )
        except ValueError:
            self._trajectory_auto_create_limit = 3

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_session(
        self,
        user_id: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PortalSession:
        """Create a new conversation session."""
        session = PortalSession(
            session_id=str(uuid4()),
            portal_id=self.config.id,
            user_id=user_id,
            metadata=metadata or {},
        )
        await self._save_session(session)
        return session

    async def get_session(self, session_id: str) -> Optional[PortalSession]:
        """Load a session by ID."""
        return await self._load_session(session_id)

    @staticmethod
    def _noop_retrieval_decision() -> Dict[str, Any]:
        return {
            "strategy": "semantic_first",
            "source": "noop",
            "rule_id": None,
            "note": None,
            "version": 1,
        }

    async def chat(
        self,
        session_id: str,
        user_message: str,
        user_id: str = "default",
        stream: bool = True,
        _route_depth: int = 0,
        _visited_portal_ids: Optional[Set[str]] = None,
    ) -> AsyncIterator[PortalEvent]:
        """
        Process a user message and stream PortalEvents.

        Args:
            session_id: Existing or new session ID
            user_message: The user's raw message
            user_id: Caller user identifier
            stream: If False, buffer and yield events in batch (still async generator)

        Yields:
            PortalEvent objects
        """
        client = self._get_client()
        intent_svc = self._get_intent_service()

        # 1. Load or create session
        session = await self._load_session(session_id)
        if not session:
            session = PortalSession(
                session_id=session_id,
                portal_id=self.config.id,
                user_id=user_id,
            )
        pending_events = self._drain_pending_events(session)
        if pending_events:
            await self._save_session(session)
            for item in pending_events:
                etype = str(item.get("type") or "").strip().lower()
                if etype not in {
                    PortalEventType.AUTO_SKILL_CREATED.value,
                    PortalEventType.AUTO_SKILL_REVISED.value,
                    PortalEventType.MEMORY_BEHAVIOR_SUGGESTION.value,
                }:
                    continue
                payload = item.get("metadata")
                meta_payload = payload if isinstance(payload, dict) else {}
                yield PortalEvent(
                    type=PortalEventType(etype),
                    session_id=session.session_id,
                    portal_id=self.config.id,
                    metadata=meta_payload,
                )

        # 2. Retrieve memories
        memories: List[PortalMemoryEntry] = []
        memory_snapshot = ""
        retrieval_decision = self._noop_retrieval_decision()
        if self.config.memory_enabled:
            try:
                memories = await self.memory_provider.retrieve(
                    portal_id=self.config.id,
                    user_id=user_id,
                    query=user_message,
                    top_k=10,
                    include_global=self.config.global_memory_enabled,
                    session_id=session_id,
                )
                memory_snapshot = await self.memory_provider.bounded_snapshot(
                    portal_id=self.config.id,
                    user_id=user_id,
                    max_chars=1200,
                    max_entries=12,
                    include_global=self.config.global_memory_enabled,
                )
            except Exception as e:
                logger.warning("[Portal] MemPalace unavailable; continue without memory: %s", e)
                memories = []
                memory_snapshot = ""

        if self._memory_behavior_suggest_enabled and memories:
            suggestions = self._memory_behavior.suggest(
                memories=memories,
                user_message=user_message,
                limit=3,
            )
            if suggestions:
                yield PortalEvent(
                    type=PortalEventType.MEMORY_BEHAVIOR_SUGGESTION,
                    session_id=session_id,
                    portal_id=self.config.id,
                    metadata={"suggestions": suggestions},
                )

        # 3. Build conversation history for context
        history = [
            {"role": m.role, "content": m.content}
            for m in session.messages[-(self.config.max_session_messages):]
        ]
        session_retrievals = await self.search_sessions(
            user_id=user_id,
            query=user_message,
            top_k=6,
            exclude_session_id=session.session_id,
        )

        # 4. Get available workflows
        available_wfs = await self._get_available_workflows()
        visited_portals: Set[str] = set(_visited_portal_ids or set())
        visited_portals.add(self.config.id)
        available_child_portals = await self._get_available_child_portals(visited_portals)
        logger.info(
            "[PortalRoute] portal=%s depth=%s child_candidates=%s workflow_candidates=%s disabled_child_ids=%s",
            self.config.id,
            _route_depth,
            [p.get("id") for p in available_child_portals],
            len(available_wfs),
            getattr(self.config, "disabled_child_portal_ids", []),
        )

        # Decide path: workflow dispatch vs backbone direct reply
        use_backbone = False
        direct_reply_when_fallback_disabled: Optional[str] = None
        intent_result: Optional[IntentUnderstandingResult] = None
        dispatched_workflow_ids: List[str] = []
        workflow_results: Dict[str, str] = {}
        child_portal_dispatched = False

        # 4.1 Child portal routing has higher priority than local workflow routing
        if available_child_portals and _route_depth < 2:
            portal_intent = await intent_svc.understand(
                user_query=user_message,
                available_children=available_child_portals,
                conversation_history=history,
                memories=memories,
                memory_snapshot=memory_snapshot,
                session_retrievals=session_retrievals,
                max_selected=max(1, int(self.config.max_portals_per_request)),
                min_relevance_score=0.65,
            )
            logger.info(
                "[PortalRoute] portal_intent selected=%s status=%s note=%s clarification_needed=%s confidence=%s",
                [p.workflow_id for p in portal_intent.dispatch_plans],
                portal_intent.routing_status,
                portal_intent.routing_note,
                portal_intent.clarification_needed,
                getattr(portal_intent, "confidence", None),
            )
            if portal_intent.dispatch_plans:
                child_portal_dispatched = True
                for plan in portal_intent.dispatch_plans:
                    dispatched_workflow_ids.append(f"portal:{plan.workflow_id}")
                    yield PortalEvent(
                        type=PortalEventType.PORTAL_DISPATCH_START,
                        session_id=session_id,
                        portal_id=self.config.id,
                        workflow_id=plan.workflow_id,
                        workflow_name=plan.workflow_name,
                        metadata={"route_depth": _route_depth + 1},
                    )
                    child_result = f"[Portal 路由失败: child portal not found: {plan.workflow_id}]"
                    child_service = None
                    if self._portal_manager:
                        child_service = await self._portal_manager.get_service(plan.workflow_id)

                    if child_service:
                        child_session = await child_service.create_session(
                            user_id=user_id,
                            metadata={"source_portal_id": self.config.id, "route_depth": _route_depth + 1},
                        )
                        child_chunks: List[str] = []
                        async for child_ev in child_service.chat(
                            session_id=child_session.session_id,
                            user_message=plan.sub_query,
                            user_id=user_id,
                            stream=True,
                            _route_depth=_route_depth + 1,
                            _visited_portal_ids=set(visited_portals),
                        ):
                            if child_ev.type == PortalEventType.CONTENT and child_ev.delta:
                                child_chunks.append(child_ev.delta)
                                continue

                            if child_ev.type in {
                                PortalEventType.INTENT_UNDERSTOOD,
                                PortalEventType.MEMORY_BEHAVIOR_SUGGESTION,
                                PortalEventType.WORKFLOW_DISPATCH_START,
                                PortalEventType.WORKFLOW_DISPATCH_RESULT,
                                PortalEventType.WORKFLOW_EXECUTION_EVENT,
                                PortalEventType.SYNTHESIS_START,
                                PortalEventType.ERROR,
                            }:
                                yield PortalEvent(
                                    type=PortalEventType.WORKFLOW_EXECUTION_EVENT,
                                    session_id=session_id,
                                    portal_id=self.config.id,
                                    workflow_id=plan.workflow_id,
                                    workflow_name=plan.workflow_name,
                                    metadata={
                                        "source": "child_portal",
                                        "child_portal_id": plan.workflow_id,
                                        "child_portal_name": plan.workflow_name,
                                        "child_event_type": child_ev.type,
                                        "child_event": child_ev.model_dump(mode="json", exclude_none=True),
                                    },
                                )

                        child_result = "".join(child_chunks).strip() or "(子 Portal 未返回内容)"
                    workflow_results[f"portal:{plan.workflow_id}"] = child_result
                    yield PortalEvent(
                        type=PortalEventType.PORTAL_DISPATCH_RESULT,
                        session_id=session_id,
                        portal_id=self.config.id,
                        workflow_id=plan.workflow_id,
                        workflow_name=plan.workflow_name,
                        workflow_result=child_result[:500],
                    )
            else:
                if portal_intent.routing_status == "filtered_by_relevance":
                    logger.info(
                        "[PortalRoute] no child portal dispatched: candidates filtered by relevance threshold. note=%s",
                        portal_intent.routing_note,
                    )
                elif portal_intent.routing_status == "intent_error":
                    logger.warning(
                        "[PortalRoute] no child portal dispatched: intent understanding failed. note=%s",
                        portal_intent.routing_note,
                    )
                else:
                    logger.info(
                        "[PortalRoute] no child portal dispatched: no relevant child matched. note=%s",
                        portal_intent.routing_note,
                    )

        if child_portal_dispatched:
            use_backbone = False
        elif not available_wfs:
            # No workflows → Backbone direct reply (if enabled)
            if self.config.fallback_to_copilot:
                use_backbone = True
            else:
                direct_reply_when_fallback_disabled = NO_WORKFLOW_FALLBACK_DISABLED_MESSAGE
        else:
            # 5. Intent understanding (using the workflow-level alias)
            intent_result = await intent_svc.understand_workflows(
                user_query=user_message,
                available_workflows=available_wfs,
                conversation_history=history,
                memories=memories,
                memory_snapshot=memory_snapshot,
                session_retrievals=session_retrievals,
                max_selected=max(1, int(self.config.max_workflows_per_request)),
            )
            if intent_result is None:
                if self.config.fallback_to_copilot:
                    use_backbone = True
                else:
                    direct_reply_when_fallback_disabled = NO_MATCH_FALLBACK_DISABLED_MESSAGE
                intent_result = IntentUnderstandingResult(
                    original_query=user_message,
                    understood_intent=user_message,
                    dispatch_plans=[],
                )

            yield PortalEvent(
                type=PortalEventType.INTENT_UNDERSTOOD,
                session_id=session_id,
                portal_id=self.config.id,
                intent=intent_result,
            )

            # If clarification needed, just ask
            if intent_result.clarification_needed:
                q = intent_result.clarification_question or "能请您进一步说明需求吗？"
                session.messages.append(PortalConversationMessage(role="user", content=user_message))
                session.messages.append(PortalConversationMessage(role="assistant", content=q))
                await self._save_session(session)
                yield PortalEvent(
                    type=PortalEventType.CONTENT,
                    session_id=session_id,
                    portal_id=self.config.id,
                    delta=q,
                )
                yield PortalEvent(
                    type=PortalEventType.COMPLETE,
                    session_id=session_id,
                    portal_id=self.config.id,
                )
                return

            # No dispatch plans → Backbone fallback
            if not intent_result.dispatch_plans:
                if self.config.fallback_to_copilot:
                    use_backbone = True
                else:
                    direct_reply_when_fallback_disabled = NO_MATCH_FALLBACK_DISABLED_MESSAGE
            else:
                # 6. Execute workflows (group by priority, parallel within group)
                offloader = PortalContextOffloader(
                    provider=self.memory_provider,
                    portal_id=self.config.id,
                    user_id=user_id,
                )
                exec_context = ExecutionContext(offloader=offloader, backend=self._local_backend)
                exec_context.metadata.update({
                    "session_id": session_id,
                    "user_id": user_id,
                    "portal_id": self.config.id,
                })

                plans_by_priority: Dict[int, List[WorkflowDispatchPlan]] = {}
                for plan in intent_result.dispatch_plans:
                    plans_by_priority.setdefault(plan.priority, []).append(plan)

                for priority in sorted(plans_by_priority.keys()):
                    group = plans_by_priority[priority]

                    for plan in group:
                        dispatched_workflow_ids.append(plan.workflow_id)
                        yield PortalEvent(
                            type=PortalEventType.WORKFLOW_DISPATCH_START,
                            session_id=session_id,
                            portal_id=self.config.id,
                            workflow_id=plan.workflow_id,
                            workflow_name=plan.workflow_name,
                        )

                    for plan in group:
                        result_text = ""
                        try:
                            async for exec_event in self._wf_manager.run_workflow_stream_events(
                                workflow_id=plan.workflow_id,
                                input_message=plan.sub_query,
                                context=exec_context,
                            ):
                                if exec_event.event_type == ExecutionEventType.NODE_COMPLETE and exec_event.content:
                                    result_text = exec_event.content
                                elif not result_text and exec_event.delta_content:
                                    result_text += exec_event.delta_content

                                yield PortalEvent(
                                    type=PortalEventType.WORKFLOW_EXECUTION_EVENT,
                                    session_id=session_id,
                                    portal_id=self.config.id,
                                    workflow_id=plan.workflow_id,
                                    workflow_name=plan.workflow_name,
                                    metadata={"execution_event": exec_event.model_dump(mode="json", exclude_none=True)},
                                )
                        except Exception as e:
                            result_text = f"[工作流 {plan.workflow_name} 执行出错: {e}]"

                        workflow_results[plan.workflow_id] = result_text or "(无输出)"
                        yield PortalEvent(
                            type=PortalEventType.WORKFLOW_DISPATCH_RESULT,
                            session_id=session_id,
                            portal_id=self.config.id,
                            workflow_id=plan.workflow_id,
                            workflow_name=plan.workflow_name,
                            workflow_result=(result_text or "(无输出)")[:500],
                        )
                for event in self._drain_runtime_auto_events(exec_context):
                    event_type = str(event.get("type") or "").strip().lower()
                    if event_type not in {
                        PortalEventType.AUTO_SKILL_REVISED.value,
                        PortalEventType.AUTO_SKILL_CREATED.value,
                    }:
                        continue
                    metadata = event.get("metadata")
                    payload = metadata if isinstance(metadata, dict) else {}
                    yield PortalEvent(
                        type=PortalEventType(event_type),
                        session_id=session_id,
                        portal_id=self.config.id,
                        metadata=payload,
                    )

        # 7. Generate response — Backbone direct or Synthesis
        if use_backbone:
            # Backbone Agent direct reply (no workflow results)
            if stream:
                backbone_chunks: List[str] = []
                async for chunk in self._backbone_reply_stream(
                    client=client,
                    user_query=user_message,
                    memories=memories,
                    memory_snapshot=memory_snapshot,
                    history=history,
                ):
                    backbone_chunks.append(chunk)
                    yield PortalEvent(
                        type=PortalEventType.CONTENT,
                        session_id=session_id,
                        portal_id=self.config.id,
                        delta=chunk,
                    )
                final_answer_for_session = "".join(backbone_chunks)
            else:
                final_answer_for_session = await self._backbone_reply(
                    client=client,
                    user_query=user_message,
                    memories=memories,
                    memory_snapshot=memory_snapshot,
                    history=history,
                )
                yield PortalEvent(
                    type=PortalEventType.CONTENT,
                    session_id=session_id,
                    portal_id=self.config.id,
                    delta=final_answer_for_session,
                )
            blocked_by_safety = False
        elif direct_reply_when_fallback_disabled is not None:
            final_answer_for_session = direct_reply_when_fallback_disabled
            yield PortalEvent(
                type=PortalEventType.CONTENT,
                session_id=session_id,
                portal_id=self.config.id,
                delta=final_answer_for_session,
            )
            blocked_by_safety = False
        else:
            # Pre-generation safety scan
            understood_intent = intent_result.understood_intent if intent_result else ""
            safety = self.pre_generation_safety_scan(
                user_query=user_message,
                intent=understood_intent,
                workflow_results=workflow_results,
                memories=memories,
                memory_snapshot=memory_snapshot,
            )
            blocked_by_safety = safety.blocked

            if blocked_by_safety:
                yield PortalEvent(
                    type=PortalEventType.SAFETY_BLOCKED,
                    session_id=session_id,
                    portal_id=self.config.id,
                    metadata=safety.model_dump(),
                )
                yield PortalEvent(
                    type=PortalEventType.CONTENT,
                    session_id=session_id,
                    portal_id=self.config.id,
                    delta=SAFETY_BLOCK_MESSAGE,
                )
                final_answer_for_session = SAFETY_BLOCK_MESSAGE
            else:
                # 8. Synthesise final answer
                yield PortalEvent(
                    type=PortalEventType.SYNTHESIS_START,
                    session_id=session_id,
                    portal_id=self.config.id,
                )

                understood_intent_str = intent_result.understood_intent if intent_result else ""

                # Stream final answer character by character (chunked)
                if stream:
                    streamed_chunks: List[str] = []
                    async for chunk in self._stream_synthesis(
                        client=client,
                        user_query=user_message,
                        intent=understood_intent_str,
                        workflow_results=workflow_results,
                        memories=memories,
                        memory_snapshot=memory_snapshot,
                        session_retrievals=session_retrievals,
                        history=history,
                    ):
                        yield PortalEvent(
                            type=PortalEventType.CONTENT,
                            session_id=session_id,
                            portal_id=self.config.id,
                            delta=chunk,
                        )
                        streamed_chunks.append(chunk)
                    final_answer_for_session = "".join(streamed_chunks).strip()
                    if not final_answer_for_session:
                        # Defensive fallback when stream unexpectedly yields no text.
                        final_answer_for_session = await self._synthesise(
                            client=client,
                            user_query=user_message,
                            intent=understood_intent_str,
                            workflow_results=workflow_results,
                            memories=memories,
                            memory_snapshot=memory_snapshot,
                            session_retrievals=session_retrievals,
                            history=history,
                        )
                else:
                    final_answer = await self._synthesise(
                        client=client,
                        user_query=user_message,
                        intent=understood_intent_str,
                        workflow_results=workflow_results,
                        memories=memories,
                        memory_snapshot=memory_snapshot,
                        session_retrievals=session_retrievals,
                        history=history,
                        stream_callback=None,
                    )
                    yield PortalEvent(
                        type=PortalEventType.CONTENT,
                        session_id=session_id,
                        portal_id=self.config.id,
                        delta=final_answer,
                    )
                    final_answer_for_session = final_answer

        # 9. Update session
        session.messages.append(PortalConversationMessage(
            role="user",
            content=user_message,
        ))
        session.messages.append(PortalConversationMessage(
            role="assistant",
            content=final_answer_for_session,
            dispatched_workflows=dispatched_workflow_ids,
        ))

        # Trim session history
        if len(session.messages) > self.config.max_session_messages * 2:
            session.messages = session.messages[-(self.config.max_session_messages * 2):]

        await self._save_session(session)

        # 10. Extract and store memories (non-blocking)
        if self.config.memory_enabled and not blocked_by_safety:
            self._spawn_background_task(
                self._extract_memories(
                    client=client,
                    session=session,
                    user_message=user_message,
                    assistant_response=final_answer_for_session,
                    user_id=user_id,
                ),
                task_name="extract_memories",
                session_id=session_id,
                user_id=user_id,
            )

        # 11. Extract trajectory signals (non-blocking, L1 precipitation)
        if not blocked_by_safety:
            self._spawn_background_task(
                self._extract_trajectory_bg(
                    session_id=session_id,
                    user_message=user_message,
                    assistant_response=final_answer_for_session,
                    dispatched_workflow_ids=dispatched_workflow_ids,
                    workflow_results=workflow_results,
                    user_id=user_id,
                ),
                task_name="extract_trajectory",
                session_id=session_id,
                user_id=user_id,
            )

        yield PortalEvent(
            type=PortalEventType.COMPLETE,
            session_id=session_id,
            portal_id=self.config.id,
        )

    # ------------------------------------------------------------------
    # Memory public helpers
    # ------------------------------------------------------------------

    async def get_memories(
        self,
        user_id: str = "default",
        query: str = "",
        top_k: int = 20,
        min_confidence: float = 0.0,
        confidence_tier: Optional[str] = None,
        include_conflicted: bool = True,
        session_id: Optional[str] = None,
    ) -> List[PortalMemoryEntry]:
        """Retrieve memories for a user."""
        try:
            return await self.memory_provider.retrieve(
                portal_id=self.config.id,
                user_id=user_id,
                query=query,
                top_k=top_k,
                include_global=self.config.global_memory_enabled,
                session_id=session_id,
            )
        except Exception as e:
            logger.warning("[Portal] get_memories failed; returning empty: %s", e)
            return []

    async def delete_memory(self, user_id: str, entry_id: str) -> bool:
        """Delete a specific memory entry."""
        try:
            await self.memory_provider.delete(
                portal_id=self.config.id,
                user_id=user_id,
                entry_id=entry_id
            )
            return True
        except Exception as e:
            logger.warning("[Portal] delete_memory failed: %s", e)
            return False

    async def clear_memories(self, user_id: str = "default") -> int:
        """Clear all memories for a user."""
        try:
            await self.memory_provider.clear(
                portal_id=self.config.id,
                user_id=user_id
            )
            return 0
        except Exception as e:
            logger.warning("[Portal] clear_memories failed: %s", e)
            return 0

    def pre_generation_safety_scan(
        self,
        *,
        user_query: str,
        intent: str,
        workflow_results: Dict[str, str],
        memories: List[PortalMemoryEntry],
        memory_snapshot: str,
    ) -> SafetyScanResult:
        """Run rule-based safety scan before final synthesis."""
        return self._safety_scanner.scan(
            user_query=user_query,
            intent=intent,
            workflow_results=workflow_results,
            memories=memories,
            memory_snapshot=memory_snapshot,
        )

    async def search_sessions(
        self,
        user_id: str,
        query: str,
        top_k: int = 8,
        exclude_session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant snippets from historical sessions.

        Returns lightweight snippets to avoid inflating prompt size.
        """
        if not query.strip() or top_k <= 0:
            return []

        query_tokens = set(self._tokenize_for_search(query))
        if not query_tokens:
            return []

        all_sessions = await self._storage.backend.list_all(SESSION_COLLECTION)
        scored: List[tuple[float, Dict[str, Any]]] = []

        for raw in all_sessions:
            try:
                s = PortalSession(**raw)
            except Exception:
                continue

            if s.portal_id != self.config.id or s.user_id != user_id:
                continue
            if exclude_session_id and s.session_id == exclude_session_id:
                continue

            for idx, msg in enumerate(s.messages):
                content = (msg.content or "").strip()
                if not content:
                    continue
                content_tokens = set(self._tokenize_for_search(content))
                if not content_tokens:
                    continue
                overlap = query_tokens & content_tokens
                if not overlap:
                    continue
                score = len(overlap) / len(query_tokens)
                snippet = content if len(content) <= 220 else f"{content[:220]}..."
                scored.append((
                    score,
                    {
                        "session_id": s.session_id,
                        "message_index": idx,
                        "role": msg.role,
                        "snippet": snippet,
                        "score": score,
                        "timestamp": msg.timestamp.isoformat(),
                    },
                ))

        scored.sort(key=lambda x: (x[0], x[1]["timestamp"]), reverse=True)
        return [item for _, item in scored[:top_k]]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                raise RuntimeError("openai package is required. Install with: pip install openai")

            kwargs: Dict[str, Any] = {}
            provider = (self.config.provider or "openai").strip().lower()
            api_key = self.config.api_key
            base_url = self.config.base_url

            # Fallback to copilot internal config when portal config does not carry secrets.
            if (not api_key or not base_url) and provider != "ollama":
                try:
                    from ..copilot import get_copilot_service

                    copilot_cfg = get_copilot_service().get_internal_config()
                    if copilot_cfg.get("provider") == provider:
                        api_key = api_key or copilot_cfg.get("api_key")
                        base_url = base_url or copilot_cfg.get("base_url")
                except Exception:
                    pass

            if not api_key and provider != "ollama":
                provider_env_keys = {
                    "openai": "OPENAI_API_KEY",
                    "zhipu": "ZHIPU_API_KEY",
                    "deepseek": "DEEPSEEK_API_KEY",
                    "qwen": "QWEN_API_KEY",
                    "moonshot": "MOONSHOT_API_KEY",
                    "anthropic": "ANTHROPIC_API_KEY",
                }
                env_key = provider_env_keys.get(provider)
                api_key = os.environ.get(env_key) if env_key else None
                if not api_key:
                    api_key = os.environ.get("OPENAI_API_KEY")

            if api_key:
                kwargs["api_key"] = api_key
            elif provider == "ollama":
                kwargs["api_key"] = "placeholder"
            else:
                raise RuntimeError(
                    f"Portal LLM api_key is not configured for provider '{provider}'. "
                    "Please configure portal api_key or copilot api_key."
                )

            if base_url:
                kwargs["base_url"] = base_url

            self._client = AsyncOpenAI(**kwargs)
        return self._client

    def _get_intent_service(self) -> IntentUnderstandingService:
        if self._intent_svc is None:
            self._intent_svc = IntentUnderstandingService(
                llm_client=self._get_client(),
                model=self.config.model,
                temperature=self.config.temperature,
            )
        return self._intent_svc

    async def _get_available_workflows(self) -> List[Dict[str, Any]]:
        """Return metadata for all workflows bound to this portal.

        If auto_include_published is True, dynamically include all published
        workflows instead of only those in workflow_ids.
        """
        result = []
        seen_ids: set = set()

        # Explicit bindings
        for wf_id in self.config.workflow_ids:
            wf = await self._wf_manager.get_workflow(wf_id)
            if wf:
                result.append({
                    "id": wf.id,
                    "name": wf.name,
                    "description": wf.description,
                })
                seen_ids.add(wf.id)

        # Auto-include published workflows
        if self.config.auto_include_published:
            published = await self._wf_manager.list_published()
            for pub in published:
                wf_id = pub.get("workflow_id") or pub.get("id", "")
                if wf_id and wf_id not in seen_ids:
                    wf = await self._wf_manager.get_workflow(wf_id)
                    if wf:
                        result.append({
                            "id": wf.id,
                            "name": wf.name,
                            "description": wf.description,
                        })
                        seen_ids.add(wf.id)

        return result

    async def _get_available_child_portals(self, exclude_ids: Set[str]) -> List[Dict[str, Any]]:
        if not self._portal_manager:
            return []
        result: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        disabled_ids = {str(pid) for pid in (self.config.disabled_child_portal_ids or []) if str(pid)}

        # Root default behavior: auto-discover all non-default portals
        if self.config.is_default and self.config.auto_discover_child_portals:
            all_portals = await self._portal_manager.list_portals()
            for cfg in all_portals:
                if cfg.id in exclude_ids or cfg.id in disabled_ids:
                    continue
                if cfg.is_default:
                    continue
                result.append({
                    "id": cfg.id,
                    "name": cfg.name,
                    "description": cfg.description,
                })
                seen_ids.add(cfg.id)

        # Explicit bindings (always honored unless excluded/disabled)
        for portal_id in self.config.child_portal_ids:
            if not portal_id or portal_id in exclude_ids:
                continue
            if portal_id in disabled_ids or portal_id in seen_ids:
                continue
            cfg = await self._portal_manager.get_portal(portal_id)
            if not cfg:
                continue
            result.append({
                "id": cfg.id,
                "name": cfg.name,
                "description": cfg.description,
            })
        return result

    async def _run_child_portal(
        self,
        child_portal_id: str,
        sub_query: str,
        user_id: str,
        route_depth: int,
        visited_portals: Set[str],
    ) -> str:
        if not self._portal_manager:
            return "[Portal 路由失败: portal_manager unavailable]"
        child_service = await self._portal_manager.get_service(child_portal_id)
        if not child_service:
            return f"[Portal 路由失败: child portal not found: {child_portal_id}]"

        child_session = await child_service.create_session(
            user_id=user_id,
            metadata={"source_portal_id": self.config.id, "route_depth": route_depth},
        )
        chunks: List[str] = []
        async for ev in child_service.chat(
            session_id=child_session.session_id,
            user_message=sub_query,
            user_id=user_id,
            stream=False,
            _route_depth=route_depth,
            _visited_portal_ids=set(visited_portals),
        ):
            if ev.type == PortalEventType.CONTENT and ev.delta:
                chunks.append(ev.delta)
        return "".join(chunks).strip() or "(子 Portal 未返回内容)"

    async def _run_workflow(
        self,
        workflow_id: str,
        sub_query: str,
        context: Optional[ExecutionContext] = None,
    ) -> str:
        """Execute a single workflow and return its text output."""
        try:
            result = await self._wf_manager.run_workflow(
                workflow_id,
                sub_query,
                context=context,
            )
            if result.error:
                return f"[错误: {result.error}]"
            if result.response and result.response.messages:
                return "\n".join(m.content for m in result.response.messages if m.content)
            return "(工作流未返回内容)"
        except Exception as e:
            logger.error(f"[Portal] Workflow {workflow_id} execution error: {e}")
            return f"[执行异常: {e}]"

    async def _backbone_reply(
        self,
        client,
        user_query: str,
        memories: List[PortalMemoryEntry],
        memory_snapshot: str,
        history: List[Dict[str, str]],
    ) -> str:
        """Backbone Agent direct reply (non-streaming) — used when no workflow matches."""
        system_prompt = self.config.backbone_system_prompt or DEFAULT_BACKBONE_SYSTEM_PROMPT
        memory_block = memory_snapshot.strip() or ""
        if memory_block:
            system_prompt += f"\n\nUser memory context:\n{memory_block}"

        messages = [
            {"role": "system", "content": system_prompt},
            *history[-6:],
            {"role": "user", "content": user_query},
        ]
        try:
            resp = await client.chat.completions.create(
                model=self.config.model,
                temperature=self.config.temperature,
                messages=messages,
                max_tokens=2048,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"[Portal] Backbone reply failed: {e}")
            return f"抱歉，处理您的请求时遇到了问题: {e}"

    async def _backbone_reply_stream(
        self,
        client,
        user_query: str,
        memories: List[PortalMemoryEntry],
        memory_snapshot: str,
        history: List[Dict[str, str]],
    ) -> AsyncIterator[str]:
        """Backbone Agent streaming reply — used when no workflow matches."""
        system_prompt = self.config.backbone_system_prompt or DEFAULT_BACKBONE_SYSTEM_PROMPT
        memory_block = memory_snapshot.strip() or ""
        if memory_block:
            system_prompt += f"\n\nUser memory context:\n{memory_block}"

        messages = [
            {"role": "system", "content": system_prompt},
            *history[-6:],
            {"role": "user", "content": user_query},
        ]
        try:
            stream = await client.chat.completions.create(
                model=self.config.model,
                temperature=self.config.temperature,
                messages=messages,
                max_tokens=2048,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"[Portal] Backbone stream reply failed: {e}")
            yield f"抱歉，处理您的请求时遇到了问题: {e}"

    def _spawn_background_task(self, coro, task_name: str, **meta: Any) -> None:
        """Spawn a detached task with explicit completion/cancel/error observability."""
        task = asyncio.create_task(coro)
        task.add_done_callback(
            lambda t: self._on_background_task_done(t, task_name=task_name, meta=meta)
        )

    def _on_background_task_done(self, task: asyncio.Task, task_name: str, meta: Dict[str, Any]) -> None:
        try:
            if task.cancelled():
                logger.info(
                    "[PortalBG] task cancelled: name=%s portal_id=%s meta=%s",
                    task_name,
                    self.config.id,
                    meta,
                )
                return
            exc = task.exception()
            if exc:
                logger.warning(
                    "[PortalBG] task failed: name=%s portal_id=%s meta=%s error=%s",
                    task_name,
                    self.config.id,
                    meta,
                    exc,
                )
            else:
                logger.debug(
                    "[PortalBG] task completed: name=%s portal_id=%s meta=%s",
                    task_name,
                    self.config.id,
                    meta,
                )
        except Exception as e:
            logger.warning(
                "[PortalBG] task callback failed: name=%s portal_id=%s error=%s",
                task_name,
                self.config.id,
                e,
            )

    async def _extract_trajectory_bg(
        self,
        session_id: str,
        user_message: str,
        assistant_response: str,
        dispatched_workflow_ids: List[str],
        workflow_results: Dict[str, str],
        user_id: str = "default",
    ) -> None:
        """
        Background task: L1 real-time trajectory signal extraction.

        - Extracts lightweight stats (tool_call_count, unique_tool_count, etc.)
        - Checks for strong signal keywords → triggers L3 immediate precipitation
        - Otherwise stores in TrajectoryPool → accumulates for L2
        """
        try:
            signals: Dict[str, Any] = {
                "tool_call_count": len(dispatched_workflow_ids),
                "unique_tool_count": len(set(dispatched_workflow_ids)),
                "error_count": sum(
                    1 for v in workflow_results.values()
                    if "[错误" in v or "[执行异常" in v
                ),
                "step_count": len(workflow_results),
            }

            # Check for strong signal keywords in user message
            if has_strong_signal(user_message):
                signals["strong_signal"] = True
                signals["precipitation_level"] = "L3"
                logger.info(
                    f"[Portal] Strong signal detected in session {session_id}, "
                    f"triggering L3 immediate precipitation"
                )
                # L3: immediately trigger artifact learning for this session
                try:
                    from ..artifacts import get_artifact_factory_service
                    factory = get_artifact_factory_service()
                    await factory.run_periodic_learning_cycle(
                        trajectories=[{
                            "session_id": session_id,
                            "user_id": user_id,
                            "messages": [
                                {"role": "user", "content": user_message},
                                {"role": "assistant", "content": assistant_response},
                            ],
                            "updated_at": datetime.now().isoformat(),
                        }],
                        min_cluster_size=1,
                        dry_run=False,
                        trigger_auto_create=self._trajectory_auto_create_enabled,
                        auto_create_limit=self._trajectory_auto_create_limit,
                    )
                except Exception as e:
                    logger.warning(f"[Portal] L3 precipitation failed: {e}")
            else:
                signals["precipitation_level"] = "L1"

            # Store in trajectory pool for L2 accumulation
            pool = get_trajectory_pool()
            pool.add(session_id, signals)

            # Check if we should trigger L2 learning cycle
            if pool.should_trigger_learning():
                entries = pool.drain()
                logger.info(
                    f"[Portal] TrajectoryPool threshold reached, "
                    f"triggering L2 learning cycle with {len(entries)} entries"
                )
                try:
                    from ..artifacts import get_artifact_factory_service
                    factory = get_artifact_factory_service()
                    trajectories = [
                        {
                            "session_id": e.session_id,
                            "user_id": "default",
                            "messages": [],
                            "updated_at": datetime.now().isoformat(),
                            "signals": e.signals,
                        }
                        for e in entries
                    ]
                    result = await factory.run_periodic_learning_cycle(
                        trajectories=trajectories,
                        min_cluster_size=2,
                        dry_run=False,
                        trigger_auto_create=self._trajectory_auto_create_enabled,
                        auto_create_limit=self._trajectory_auto_create_limit,
                    )
                    await self._store_auto_skill_notifications(
                        session_id=session_id,
                        result=result,
                    )
                except Exception as e:
                    logger.warning(f"[Portal] L2 learning cycle failed: {e}")

        except asyncio.CancelledError:
            logger.info(
                "[PortalBG] trajectory extraction cancelled: portal_id=%s session_id=%s",
                self.config.id,
                session_id,
            )
            raise
        except Exception as e:
            logger.error(f"[Portal] Trajectory extraction error: {e}")

    async def _store_auto_skill_notifications(
        self,
        *,
        session_id: str,
        result: Dict[str, Any],
    ) -> None:
        auto_creation = result.get("auto_controlled_creation") if isinstance(result, dict) else {}
        if not isinstance(auto_creation, dict):
            return
        created_count = int(auto_creation.get("auto_created_count") or 0)
        if created_count <= 0:
            return
        items = auto_creation.get("items")
        if not isinstance(items, list):
            return
        session = await self._load_session(session_id)
        if not session:
            return
        bucket = session.metadata.get(PENDING_EVENTS_KEY)
        if not isinstance(bucket, list):
            bucket = []
        for item in items:
            if not isinstance(item, dict) or not item.get("auto_created"):
                continue
            bucket.append(
                {
                    "type": PortalEventType.AUTO_SKILL_CREATED.value,
                    "metadata": {
                        "candidate_id": item.get("candidate_id"),
                        "rollout_status": item.get("rollout_status"),
                        "assessment": item.get("assessment"),
                    },
                }
            )
        if not bucket:
            return
        session.metadata[PENDING_EVENTS_KEY] = bucket[-20:]
        await self._save_session(session)

    @staticmethod
    def _drain_pending_events(session: PortalSession) -> List[Dict[str, Any]]:
        data = session.metadata if isinstance(session.metadata, dict) else {}
        session.metadata = data
        items = data.get(PENDING_EVENTS_KEY)
        if not isinstance(items, list):
            return []
        data[PENDING_EVENTS_KEY] = []
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _drain_runtime_auto_events(context: ExecutionContext) -> List[Dict[str, Any]]:
        data = context.metadata if isinstance(context.metadata, dict) else {}
        context.metadata = data
        raw = data.get("auto_revision_notifications")
        if not isinstance(raw, list):
            return []
        data["auto_revision_notifications"] = []
        out: List[Dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "type": item.get("type") or PortalEventType.AUTO_SKILL_REVISED.value,
                    "metadata": {
                        "candidate_id": item.get("candidate_id"),
                        "tool_name": item.get("tool_name"),
                        "error_type": item.get("error_type"),
                        "rollout_status": item.get("rollout_status"),
                    },
                }
            )
        return out

    async def _synthesise(
        self,
        client,
        user_query: str,
        intent: str,
        workflow_results: Dict[str, str],
        memories: List[PortalMemoryEntry],
        memory_snapshot: str,
        session_retrievals: List[Dict[str, Any]],
        history: List[Dict[str, str]],
        stream_callback=None,
    ) -> str:
        """Call LLM to synthesise a final answer (non-streaming)."""
        user_content = self._build_synthesis_prompt(
            user_query,
            intent,
            workflow_results,
            memories,
            memory_snapshot=memory_snapshot,
            session_retrievals=session_retrievals,
        )
        messages = [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            *history[-6:],
            {"role": "user", "content": user_content},
        ]
        try:
            resp = await client.chat.completions.create(
                model=self.config.model,
                temperature=0.5,
                messages=messages,
                max_tokens=2048,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"[Portal] Synthesis failed: {e}")
            # Fallback: concatenate workflow results
            parts = [f"**{wf_id}**: {text}" for wf_id, text in workflow_results.items()]
            return "\n\n".join(parts)

    async def _stream_synthesis(
        self,
        client,
        user_query: str,
        intent: str,
        workflow_results: Dict[str, str],
        memories: List[PortalMemoryEntry],
        memory_snapshot: str,
        session_retrievals: List[Dict[str, Any]],
        history: List[Dict[str, str]],
    ) -> AsyncIterator[str]:
        """Stream synthesis chunks."""
        user_content = self._build_synthesis_prompt(
            user_query,
            intent,
            workflow_results,
            memories,
            memory_snapshot=memory_snapshot,
            session_retrievals=session_retrievals,
        )
        messages = [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            *history[-6:],
            {"role": "user", "content": user_content},
        ]
        try:
            stream = await client.chat.completions.create(
                model=self.config.model,
                temperature=0.5,
                messages=messages,
                max_tokens=2048,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"[Portal] Stream synthesis failed: {e}")
            for wf_id, text in workflow_results.items():
                yield f"\n**{wf_id}**: {text}"

    @staticmethod
    def _build_synthesis_prompt(
        user_query: str,
        intent: str,
        workflow_results: Dict[str, str],
        memories: List[PortalMemoryEntry],
        memory_snapshot: str = "",
        session_retrievals: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        memory_block = "\n".join(f"- {m.content}" for m in memories) or "(none)"
        bounded_memory_block = memory_snapshot.strip() or "(none)"
        retrieval_block = "\n".join(
            f"- session={r.get('session_id')} role={r.get('role')}: {r.get('snippet', '')}"
            for r in (session_retrievals or [])
        ) or "(none)"
        results_block = "\n\n".join(
            f"### Workflow `{wf_id}` result:\n{text}"
            for wf_id, text in workflow_results.items()
        ) or "(no results)"

        return f"""User intent: {intent}

Bounded memory snapshot:
{bounded_memory_block}

User memory context:
{memory_block}

Retrieved related session snippets:
{retrieval_block}

Workflow results:
{results_block}

Original user message:
{user_query}

Please synthesise the above into a helpful, integrated response."""

    @staticmethod
    def _tokenize_for_search(text: str) -> List[str]:
        text = text.lower()
        tokens: List[str] = []
        tokens.extend(re.findall(r"[a-z0-9]+", text))
        for chunk in re.findall(r"[\u4e00-\u9fff]+", text):
            tokens.extend(list(chunk))
        return tokens

    async def _extract_memories(
        self,
        client,
        session: PortalSession,
        user_message: str,
        assistant_response: str,
        user_id: str,
    ) -> None:
        """Background task: extract memories from the latest conversation turn."""
        try:
            await self.memory_provider.write_turn(
                portal_id=self.config.id,
                user_id=user_id,
                session_id=session.session_id,
                user_message=user_message,
                assistant_response=assistant_response,
            )
            logger.debug("[Portal] Extracted memories via MemPalace.")
        except asyncio.CancelledError:
            logger.info(
                "[PortalBG] memory extraction cancelled: portal_id=%s session_id=%s user_id=%s",
                self.config.id,
                session.session_id,
                user_id,
            )
            raise
        except Exception as e:
            logger.error(f"[Portal] Memory extraction error: {e}")

    async def _save_session(self, session: PortalSession) -> None:
        session.updated_at = datetime.now()
        data = session.model_dump()
        for field in ("created_at", "updated_at"):
            if isinstance(data.get(field), datetime):
                data[field] = data[field].isoformat()
        # Serialise nested datetimes in messages
        for msg in data.get("messages", []):
            if isinstance(msg.get("timestamp"), datetime):
                msg["timestamp"] = msg["timestamp"].isoformat()
        await self._storage.backend.save(SESSION_COLLECTION, session.session_id, data)

    async def _load_session(self, session_id: str) -> Optional[PortalSession]:
        try:
            data = await self._storage.backend.load(SESSION_COLLECTION, session_id)
            if data:
                return PortalSession(**data)
        except Exception as e:
            logger.warning(f"[Portal] Session load failed: {e}")
        return None


# ============================================================
# Portal Manager — manages multiple portal instances
# ============================================================

class PortalManager:
    """
    Manages the lifecycle of all Super Portal instances.

    - CRUD for SuperPortalConfig (persisted in storage)
    - Creates PortalService instances on demand
    """

    def __init__(self):
        self._portals: Dict[str, SuperPortalConfig] = {}
        self._services: Dict[str, PortalService] = {}
        self._storage: Optional[StorageManager] = None
        self._wf_manager: Optional[WorkflowManager] = None
        self._loaded = False
        self._ready_lock = asyncio.Lock()
        self._portal_lock = asyncio.Lock()

    async def _ensure_ready(self):
        if self._storage is not None and self._wf_manager is not None and self._loaded:
            return
        async with self._ready_lock:
            if self._storage is None:
                from ..storage import initialize_storage
                self._storage = await initialize_storage()
            if self._wf_manager is None:
                self._wf_manager = get_workflow_manager()
                await self._wf_manager._ensure_storage()
            if not self._loaded:
                await self._load_all()
                self._loaded = True

    async def _load_all(self):
        try:
            if self._storage is None:
                return
            items = await self._storage.backend.list_all(PORTAL_COLLECTION)
            for item in items:
                try:
                    cfg = SuperPortalConfig(**item)
                    self._portals[cfg.id] = cfg
                except Exception as e:
                    logger.warning(f"[PortalManager] Skipping malformed portal: {e}")
            await self._normalize_default_portal_uniqueness_locked()
            logger.info(f"[PortalManager] Loaded {len(self._portals)} portals")
        except Exception as e:
            logger.error(f"[PortalManager] Load failed: {e}")

    async def _unset_other_defaults_locked(self, keep_portal_id: str) -> None:
        """Ensure only one portal keeps is_default=True. Caller must hold _portal_lock."""
        changed = 0
        now = datetime.now()
        for cfg in self._portals.values():
            if cfg.id != keep_portal_id and cfg.is_default:
                cfg.is_default = False
                cfg.updated_at = now
                await self._save_config(cfg)
                changed += 1
        if changed:
            logger.info(
                f"[PortalManager] Cleared is_default on {changed} portal(s), keep={keep_portal_id}"
            )

    async def _normalize_default_portal_uniqueness_locked(self) -> None:
        """
        Repair duplicate defaults on load.

        Keep the most recently updated default portal and clear others.
        """
        defaults = [cfg for cfg in self._portals.values() if cfg.is_default]
        if len(defaults) <= 1:
            return
        defaults.sort(key=lambda c: (c.updated_at, c.created_at), reverse=True)
        keeper = defaults[0]
        changed = 0
        for cfg in defaults[1:]:
            cfg.is_default = False
            cfg.updated_at = datetime.now()
            await self._save_config(cfg)
            changed += 1
        logger.warning(
            f"[PortalManager] Found {len(defaults)} default portals on load; "
            f"kept {keeper.id}, reset {changed} duplicates"
        )

    async def _save_config(self, config: SuperPortalConfig):
        if self._storage is None:
            raise RuntimeError("Storage is not initialised")
        data = config.model_dump()
        for field in ("created_at", "updated_at"):
            if isinstance(data.get(field), datetime):
                data[field] = data[field].isoformat()
        await self._storage.backend.save(PORTAL_COLLECTION, config.id, data)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def _create_portal_locked(
        self,
        name: str,
        description: str = "",
        workflow_ids: Optional[List[str]] = None,
        child_portal_ids: Optional[List[str]] = None,
        provider: str = "openai",
        model: str = "gpt-4",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        memory_enabled: bool = True,
        global_memory_enabled: bool = False,
        memory_provider: str = "mempalace",
        mempalace_palace_path: Optional[str] = None,
        mempalace_command: str = "mempalace",
        mempalace_args: Optional[List[str]] = None,
        mempalace_env: Optional[Dict[str, str]] = None,
        mempalace_wing_strategy: str = "per_user",
        mempalace_default_room: str = "general",
        is_default: bool = False,
        auto_include_published: bool = False,
        auto_discover_child_portals: bool = True,
        disabled_child_portal_ids: Optional[List[str]] = None,
        max_portals_per_request: int = 1,
        max_workflows_per_request: int = 3,
        fallback_to_copilot: bool = True,
        backbone_system_prompt: str = DEFAULT_BACKBONE_SYSTEM_PROMPT,
        workspace_dir: Optional[str] = None,
    ) -> SuperPortalConfig:
        """Create and persist a new Super Portal configuration. Caller must hold _portal_lock."""
        config = SuperPortalConfig(
            id=str(uuid4()),
            name=name,
            description=description,
            workflow_ids=workflow_ids or [],
            child_portal_ids=child_portal_ids or [],
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            memory_enabled=memory_enabled,
            global_memory_enabled=global_memory_enabled,
            memory_provider=str(memory_provider or "local").strip().lower(),
            mempalace_palace_path=mempalace_palace_path,
            mempalace_command=mempalace_command,
            mempalace_args=mempalace_args or ["-m", "mempalace.mcp_server"],
            mempalace_env=mempalace_env or {},
            mempalace_wing_strategy=str(mempalace_wing_strategy or "per_user").strip().lower(),
            mempalace_default_room=mempalace_default_room or "general",
            api_key_access=f"portal_{secrets.token_urlsafe(24)}",
            is_default=is_default,
            auto_include_published=auto_include_published,
            auto_discover_child_portals=auto_discover_child_portals,
            disabled_child_portal_ids=disabled_child_portal_ids or [],
            max_portals_per_request=max(1, int(max_portals_per_request)),
            max_workflows_per_request=max(1, int(max_workflows_per_request)),
            fallback_to_copilot=fallback_to_copilot,
            backbone_system_prompt=backbone_system_prompt,
            workspace_dir=workspace_dir,
        )

        self._portals[config.id] = config
        if config.is_default:
            await self._unset_other_defaults_locked(config.id)
        await self._save_config(config)
        logger.info(f"[PortalManager] Created portal {config.id}: {name}")
        return config

    async def create_portal(
        self,
        name: str,
        description: str = "",
        workflow_ids: Optional[List[str]] = None,
        child_portal_ids: Optional[List[str]] = None,
        provider: str = "openai",
        model: str = "gpt-4",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        memory_enabled: bool = True,
        global_memory_enabled: bool = False,
        memory_provider: str = "mempalace",
        mempalace_palace_path: Optional[str] = None,
        mempalace_command: str = "mempalace",
        mempalace_args: Optional[List[str]] = None,
        mempalace_env: Optional[Dict[str, str]] = None,
        mempalace_wing_strategy: str = "per_user",
        mempalace_default_room: str = "general",
        is_default: bool = False,
        auto_include_published: bool = False,
        auto_discover_child_portals: bool = True,
        disabled_child_portal_ids: Optional[List[str]] = None,
        max_portals_per_request: int = 1,
        max_workflows_per_request: int = 3,
        fallback_to_copilot: bool = True,
        backbone_system_prompt: str = DEFAULT_BACKBONE_SYSTEM_PROMPT,
        workspace_dir: Optional[str] = None,
    ) -> SuperPortalConfig:
        """Create and persist a new Super Portal configuration."""
        await self._ensure_ready()
        async with self._portal_lock:
            return await self._create_portal_locked(
                name=name,
                description=description,
                workflow_ids=workflow_ids,
                child_portal_ids=child_portal_ids,
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                memory_enabled=memory_enabled,
                global_memory_enabled=global_memory_enabled,
                memory_provider=memory_provider,
                mempalace_palace_path=mempalace_palace_path,
                mempalace_command=mempalace_command,
                mempalace_args=mempalace_args,
                mempalace_env=mempalace_env,
                mempalace_wing_strategy=mempalace_wing_strategy,
                mempalace_default_room=mempalace_default_room,
                is_default=is_default,
                auto_include_published=auto_include_published,
                auto_discover_child_portals=auto_discover_child_portals,
                disabled_child_portal_ids=disabled_child_portal_ids,
                max_portals_per_request=max_portals_per_request,
                max_workflows_per_request=max_workflows_per_request,
                fallback_to_copilot=fallback_to_copilot,
                backbone_system_prompt=backbone_system_prompt,
                workspace_dir=workspace_dir,
            )

    async def get_portal(self, portal_id: str) -> Optional[SuperPortalConfig]:
        await self._ensure_ready()
        return self._portals.get(portal_id)

    async def list_portals(self) -> List[SuperPortalConfig]:
        await self._ensure_ready()
        return list(self._portals.values())

    async def update_portal(
        self,
        portal_id: str,
        updates: Dict[str, Any],
    ) -> Optional[SuperPortalConfig]:
        await self._ensure_ready()
        async with self._portal_lock:
            config = self._portals.get(portal_id)
            if not config:
                return None

            allowed = {
                "name", "description", "workflow_ids", "child_portal_ids",
                "provider", "model", "api_key", "base_url",
                "memory_enabled", "global_memory_enabled",
                "memory_provider", "mempalace_palace_path", "mempalace_command",
                "mempalace_args", "mempalace_env", "mempalace_wing_strategy",
                "mempalace_default_room",
                "max_session_messages", "session_ttl_hours", "public",
                "is_default", "auto_include_published", "fallback_to_copilot",
                "auto_discover_child_portals", "disabled_child_portal_ids",
                "max_portals_per_request", "max_workflows_per_request",
                "backbone_system_prompt",
                "workspace_dir",
            }
            for k, v in updates.items():
                if k in allowed:
                    setattr(config, k, v)

            if config.is_default:
                await self._unset_other_defaults_locked(portal_id)
            config.updated_at = datetime.now()
            # Invalidate cached service so it picks up new config
            self._services.pop(portal_id, None)

            await self._save_config(config)
            return config

    async def delete_portal(self, portal_id: str) -> bool:
        await self._ensure_ready()
        if self._storage is None:
            return False
        async with self._portal_lock:
            if portal_id in self._portals:
                del self._portals[portal_id]
                self._services.pop(portal_id, None)
                await self._storage.backend.delete(PORTAL_COLLECTION, portal_id)
                logger.info(f"[PortalManager] Deleted portal {portal_id}")
                return True
            return False

    # ------------------------------------------------------------------
    # Default Portal
    # ------------------------------------------------------------------

    async def get_default_portal(self) -> Optional[SuperPortalConfig]:
        """Return the portal marked as is_default=True, if any."""
        await self._ensure_ready()
        defaults = [cfg for cfg in self._portals.values() if cfg.is_default]
        if not defaults:
            return None
        defaults.sort(key=lambda c: (c.updated_at, c.created_at), reverse=True)
        return defaults[0]

    async def ensure_default_portal(self) -> SuperPortalConfig:
        """
        Ensure a default Root Portal exists.

        If no portal has is_default=True, create one using LLM config
        from the Copilot service.
        """
        await self._ensure_ready()
        async with self._portal_lock:
            existing = await self.get_default_portal()
            if existing:
                logger.info(f"[PortalManager] Default portal already exists: {existing.id}")
                return existing

            # Get LLM config from Copilot
            provider = "openai"
            model = "gpt-4"
            api_key = None
            base_url = None
            try:
                from ..copilot import get_copilot_service
                copilot = get_copilot_service()
                copilot_cfg = copilot.get_internal_config()
                provider = copilot_cfg.get("provider", provider)
                model = copilot_cfg.get("model", model)
                api_key = copilot_cfg.get("api_key", api_key)
                base_url = copilot_cfg.get("base_url", base_url)
            except Exception as e:
                logger.warning(f"[PortalManager] Could not load Copilot config: {e}")

            config = await self._create_portal_locked(
                name="Root Portal",
                description="系统默认入口，自带通用 AI 对话能力，自动纳入所有已发布工作流",
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                is_default=True,
                auto_include_published=True,
                fallback_to_copilot=True,
                backbone_system_prompt=DEFAULT_BACKBONE_SYSTEM_PROMPT,
            )
            logger.info(f"[PortalManager] Created default Root Portal: {config.id}")
            return config

    # ------------------------------------------------------------------
    # Service access
    # ------------------------------------------------------------------

    async def get_service(self, portal_id: str) -> Optional[PortalService]:
        """Get (or lazily create) the PortalService for a portal."""
        await self._ensure_ready()
        if self._storage is None or self._wf_manager is None:
            return None
        config = self._portals.get(portal_id)
        if not config:
            return None

        if portal_id not in self._services:
            self._services[portal_id] = PortalService(
                config=config,
                workflow_manager=self._wf_manager,
                storage=self._storage,
                portal_manager=self,
            )

        return self._services[portal_id]

    async def get_by_access_key(self, access_key: str) -> Optional[SuperPortalConfig]:
        """Lookup portal by its API access key."""
        await self._ensure_ready()
        for cfg in self._portals.values():
            if cfg.api_key_access == access_key:
                return cfg
        return None


# ------------------------------------------------------------------
# Global singleton
# ------------------------------------------------------------------

_global_portal_manager: Optional[PortalManager] = None


def get_portal_manager() -> PortalManager:
    global _global_portal_manager
    if _global_portal_manager is None:
        _global_portal_manager = PortalManager()
    return _global_portal_manager
