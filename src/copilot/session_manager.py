"""
Session management for Copilot conversations.

Provides in-memory session storage with CRUD operations.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

from ..core.models import CopilotMessage, CopilotSession

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages copilot conversation sessions.

    Provides:
    - Session creation and retrieval
    - Message history management
    - Session cleanup
    """

    def __init__(self):
        self._sessions: Dict[str, CopilotSession] = {}

    async def create_session(self, metadata: Optional[Dict] = None) -> CopilotSession:
        """
        Create a new copilot session.

        Args:
            metadata: Optional metadata for the session

        Returns:
            Created CopilotSession
        """
        session_id = str(uuid4())
        session = CopilotSession(
            session_id=session_id,
            metadata=metadata or {},
        )
        self._sessions[session_id] = session
        logger.info(f"Created copilot session: {session_id}")
        return session

    async def get_session(self, session_id: str) -> Optional[CopilotSession]:
        """
        Get a session by ID.

        Args:
            session_id: The session ID

        Returns:
            CopilotSession if found, None otherwise
        """
        return self._sessions.get(session_id)

    async def get_or_create(
        self,
        session_id: str,
        metadata: Optional[Dict] = None
    ) -> CopilotSession:
        """
        Get an existing session or create a new one.

        Args:
            session_id: The session ID
            metadata: Optional metadata for new session

        Returns:
            CopilotSession
        """
        session = self._sessions.get(session_id)
        if session:
            return session

        session = CopilotSession(
            session_id=session_id,
            metadata=metadata or {},
        )
        self._sessions[session_id] = session
        logger.info(f"Created copilot session on demand: {session_id}")
        return session

    async def save(self, session: CopilotSession) -> None:
        """
        Save/update a session.

        Args:
            session: The session to save
        """
        session.updated_at = datetime.now()
        self._sessions[session.session_id] = session

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        tool_results: Optional[List[Dict]] = None,
    ) -> Optional[CopilotMessage]:
        """
        Add a message to a session.

        Args:
            session_id: The session ID
            role: Message role (user, assistant, tool)
            content: Message content
            tool_calls: Optional tool calls
            tool_results: Optional tool results

        Returns:
            Created CopilotMessage if session found
        """
        session = self._sessions.get(session_id)
        if not session:
            return None

        message = CopilotMessage(
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_results=tool_results,
        )
        session.messages.append(message)
        session.updated_at = datetime.now()
        return message

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: The session ID

        Returns:
            True if session was deleted
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Deleted copilot session: {session_id}")
            return True
        return False

    async def list_sessions(self) -> List[CopilotSession]:
        """
        List all active sessions.

        Returns:
            List of all CopilotSessions
        """
        return list(self._sessions.values())

    async def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """
        Clean up sessions older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours

        Returns:
            Number of sessions cleaned up
        """
        now = datetime.now()
        to_delete = []

        for session_id, session in self._sessions.items():
            age_hours = (now - session.updated_at).total_seconds() / 3600
            if age_hours > max_age_hours:
                to_delete.append(session_id)

        for session_id in to_delete:
            del self._sessions[session_id]

        if to_delete:
            logger.info(f"Cleaned up {len(to_delete)} old copilot sessions")

        return len(to_delete)
