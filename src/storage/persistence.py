"""
Persistence layer for Proton Agent Platform.

Supports:
- File-based JSON storage (default, for development)
- SQLite database storage
- PostgreSQL database storage (production)
"""

import json
import logging
import os
import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar
from uuid import uuid4

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the storage backend."""
        pass

    @abstractmethod
    async def save(self, collection: str, id: str, data: Dict[str, Any]) -> None:
        """Save an item to storage."""
        pass

    @abstractmethod
    async def load(self, collection: str, id: str) -> Optional[Dict[str, Any]]:
        """Load an item from storage."""
        pass

    @abstractmethod
    async def delete(self, collection: str, id: str) -> bool:
        """Delete an item from storage."""
        pass

    @abstractmethod
    async def list_all(self, collection: str) -> List[Dict[str, Any]]:
        """List all items in a collection."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the storage backend."""
        pass


class FileStorageBackend(StorageBackend):
    """
    File-based JSON storage backend.

    Stores each collection in a separate directory,
    with each item as a JSON file.

    Structure:
    data/
    ├── workflows/
    │   ├── {workflow_id}.json
    │   └── ...
    ├── templates/
    │   ├── {template_id}.json
    │   └── ...
    └── plugins/
        └── ...
    """

    def __init__(self, base_path: str = "./data"):
        self.base_path = Path(base_path)
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Create base directory structure."""
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized file storage at: {self.base_path.absolute()}")

    def _get_collection_path(self, collection: str) -> Path:
        """Get the path for a collection."""
        path = self.base_path / collection
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _get_item_path(self, collection: str, id: str) -> Path:
        """Get the path for an item."""
        return self._get_collection_path(collection) / f"{id}.json"

    async def save(self, collection: str, id: str, data: Dict[str, Any]) -> None:
        """Save an item to a JSON file."""
        async with self._lock:
            path = self._get_item_path(collection, id)

            # Add metadata
            data["_id"] = id
            data["_updated_at"] = datetime.now().isoformat()
            if "_created_at" not in data:
                data["_created_at"] = data["_updated_at"]

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)

            logger.debug(f"Saved {collection}/{id}")

    async def load(self, collection: str, id: str) -> Optional[Dict[str, Any]]:
        """Load an item from a JSON file."""
        path = self._get_item_path(collection, id)

        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {collection}/{id}: {e}")
            return None

    async def delete(self, collection: str, id: str) -> bool:
        """Delete a JSON file."""
        async with self._lock:
            path = self._get_item_path(collection, id)

            if path.exists():
                path.unlink()
                logger.debug(f"Deleted {collection}/{id}")
                return True
            return False

    async def list_all(self, collection: str) -> List[Dict[str, Any]]:
        """List all items in a collection."""
        path = self._get_collection_path(collection)
        items = []

        for file_path in path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    items.append(json.load(f))
            except Exception as e:
                logger.error(f"Error loading {file_path}: {e}")

        return items

    async def close(self) -> None:
        """No cleanup needed for file storage."""
        pass


class SQLiteStorageBackend(StorageBackend):
    """
    SQLite database storage backend.

    Uses aiosqlite for async operations.
    """

    def __init__(self, db_path: str = "./data/proton.db"):
        self.db_path = db_path
        self._db = None

    async def initialize(self) -> None:
        """Create database and tables."""
        try:
            import aiosqlite
        except ImportError:
            raise ImportError("aiosqlite is required for SQLite storage. Install with: pip install aiosqlite")

        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)

        # Create tables
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS items (
                collection TEXT NOT NULL,
                id TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (collection, id)
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_collection ON items(collection)
        """)
        await self._db.commit()

        logger.info(f"Initialized SQLite storage at: {self.db_path}")

    async def save(self, collection: str, id: str, data: Dict[str, Any]) -> None:
        """Save an item to the database."""
        if not self._db:
            raise RuntimeError("Database not initialized")

        now = datetime.now().isoformat()
        data_json = json.dumps(data, ensure_ascii=False, default=str)

        await self._db.execute("""
            INSERT OR REPLACE INTO items (collection, id, data, created_at, updated_at)
            VALUES (?, ?, ?, COALESCE((SELECT created_at FROM items WHERE collection = ? AND id = ?), ?), ?)
        """, (collection, id, data_json, collection, id, now, now))
        await self._db.commit()

    async def load(self, collection: str, id: str) -> Optional[Dict[str, Any]]:
        """Load an item from the database."""
        if not self._db:
            raise RuntimeError("Database not initialized")

        async with self._db.execute(
            "SELECT data FROM items WHERE collection = ? AND id = ?",
            (collection, id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None

    async def delete(self, collection: str, id: str) -> bool:
        """Delete an item from the database."""
        if not self._db:
            raise RuntimeError("Database not initialized")

        cursor = await self._db.execute(
            "DELETE FROM items WHERE collection = ? AND id = ?",
            (collection, id)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def list_all(self, collection: str) -> List[Dict[str, Any]]:
        """List all items in a collection."""
        if not self._db:
            raise RuntimeError("Database not initialized")

        items = []
        async with self._db.execute(
            "SELECT data FROM items WHERE collection = ? ORDER BY updated_at DESC",
            (collection,)
        ) as cursor:
            async for row in cursor:
                items.append(json.loads(row[0]))

        return items

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None


class PostgresStorageBackend(StorageBackend):
    """
    PostgreSQL database storage backend.

    Uses asyncpg for async operations.
    """

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self._pool = None

    async def initialize(self) -> None:
        """Create connection pool and tables."""
        try:
            import asyncpg
        except ImportError:
            raise ImportError("asyncpg is required for PostgreSQL storage. Install with: pip install asyncpg")

        self._pool = await asyncpg.create_pool(self.connection_string)

        # Create tables
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    collection TEXT NOT NULL,
                    id TEXT NOT NULL,
                    data JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (collection, id)
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_items_collection ON items(collection)
            """)

        logger.info("Initialized PostgreSQL storage")

    async def save(self, collection: str, id: str, data: Dict[str, Any]) -> None:
        """Save an item to the database."""
        if not self._pool:
            raise RuntimeError("Database not initialized")

        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO items (collection, id, data, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (collection, id)
                DO UPDATE SET data = $3, updated_at = NOW()
            """, collection, id, json.dumps(data, default=str))

    async def load(self, collection: str, id: str) -> Optional[Dict[str, Any]]:
        """Load an item from the database."""
        if not self._pool:
            raise RuntimeError("Database not initialized")

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data FROM items WHERE collection = $1 AND id = $2",
                collection, id
            )
            if row:
                return json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
            return None

    async def delete(self, collection: str, id: str) -> bool:
        """Delete an item from the database."""
        if not self._pool:
            raise RuntimeError("Database not initialized")

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM items WHERE collection = $1 AND id = $2",
                collection, id
            )
            return result == "DELETE 1"

    async def list_all(self, collection: str) -> List[Dict[str, Any]]:
        """List all items in a collection."""
        if not self._pool:
            raise RuntimeError("Database not initialized")

        items = []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT data FROM items WHERE collection = $1 ORDER BY updated_at DESC",
                collection
            )
            for row in rows:
                data = row["data"]
                items.append(json.loads(data) if isinstance(data, str) else data)

        return items

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None


class StorageManager:
    """
    Unified storage manager for Proton.

    Provides high-level CRUD operations with
    automatic serialization/deserialization.
    """

    # Collection names
    WORKFLOWS = "workflows"
    TEMPLATES = "templates"
    PLUGINS = "plugins"
    AGENTS = "agents"
    CONFIGS = "configs"  # 全局配置存储 (email, search, copilot)

    def __init__(self, backend: StorageBackend):
        self.backend = backend
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the storage manager."""
        if self._initialized:
            return

        await self.backend.initialize()
        self._initialized = True

    async def close(self) -> None:
        """Close the storage manager."""
        await self.backend.close()
        self._initialized = False

    # ============== Workflows ==============

    async def save_workflow(self, workflow_data: Dict[str, Any]) -> str:
        """Save a workflow."""
        workflow_id = workflow_data.get("id") or str(uuid4())
        workflow_data["id"] = workflow_id
        await self.backend.save(self.WORKFLOWS, workflow_id, workflow_data)
        return workflow_id

    async def load_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Load a workflow by ID."""
        return await self.backend.load(self.WORKFLOWS, workflow_id)

    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow."""
        return await self.backend.delete(self.WORKFLOWS, workflow_id)

    async def list_workflows(self) -> List[Dict[str, Any]]:
        """List all workflows."""
        return await self.backend.list_all(self.WORKFLOWS)

    # ============== Templates ==============

    async def save_template(self, template_data: Dict[str, Any]) -> str:
        """Save a template."""
        template_id = template_data.get("id") or str(uuid4())
        template_data["id"] = template_id
        await self.backend.save(self.TEMPLATES, template_id, template_data)
        return template_id

    async def load_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Load a template by ID."""
        return await self.backend.load(self.TEMPLATES, template_id)

    async def delete_template(self, template_id: str) -> bool:
        """Delete a template."""
        return await self.backend.delete(self.TEMPLATES, template_id)

    async def list_templates(self) -> List[Dict[str, Any]]:
        """List all templates."""
        return await self.backend.list_all(self.TEMPLATES)

    # ============== Plugins ==============

    async def save_plugin_config(self, plugin_id: str, config: Dict[str, Any]) -> None:
        """Save plugin configuration."""
        await self.backend.save(self.PLUGINS, plugin_id, config)

    async def load_plugin_config(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        """Load plugin configuration."""
        return await self.backend.load(self.PLUGINS, plugin_id)

    async def delete_plugin_config(self, plugin_id: str) -> bool:
        """Delete plugin configuration."""
        return await self.backend.delete(self.PLUGINS, plugin_id)

    async def list_plugin_configs(self) -> List[Dict[str, Any]]:
        """List all plugin configurations."""
        return await self.backend.list_all(self.PLUGINS)

    # ============== Global Configs ==============

    async def save_config(self, config_type: str, config_data: Dict[str, Any]) -> None:
        """
        Save global configuration.

        Args:
            config_type: Type of config ("email", "search", "copilot")
            config_data: Configuration data
        """
        await self.backend.save(self.CONFIGS, config_type, config_data)

    async def load_config(self, config_type: str) -> Optional[Dict[str, Any]]:
        """
        Load global configuration.

        Args:
            config_type: Type of config ("email", "search", "copilot")

        Returns:
            Configuration data or None if not found
        """
        return await self.backend.load(self.CONFIGS, config_type)

    async def delete_config(self, config_type: str) -> bool:
        """Delete global configuration."""
        return await self.backend.delete(self.CONFIGS, config_type)

    async def list_configs(self) -> List[Dict[str, Any]]:
        """List all global configurations."""
        return await self.backend.list_all(self.CONFIGS)


# ============== Global Storage Instance ==============

_storage_manager: Optional[StorageManager] = None


def get_storage_manager() -> StorageManager:
    """Get the global storage manager instance."""
    global _storage_manager

    if _storage_manager is None:
        # Default to SQLite storage
        # Can be changed via environment variables
        storage_type = os.environ.get("PROTON_STORAGE_TYPE", "sqlite")
        storage_path = os.environ.get("PROTON_STORAGE_PATH", "./data")

        if storage_type == "file":
            backend = FileStorageBackend(storage_path)
        elif storage_type == "sqlite":
            db_path = os.environ.get("PROTON_SQLITE_PATH", f"{storage_path}/proton.db")
            backend = SQLiteStorageBackend(db_path)
        elif storage_type == "postgres":
            conn_str = os.environ.get("PROTON_POSTGRES_URL")
            if not conn_str:
                raise ValueError("PROTON_POSTGRES_URL is required for PostgreSQL storage")
            backend = PostgresStorageBackend(conn_str)
        else:
            raise ValueError(f"Unknown storage type: {storage_type}")

        _storage_manager = StorageManager(backend)

    return _storage_manager


async def initialize_storage() -> StorageManager:
    """Initialize and return the storage manager."""
    manager = get_storage_manager()
    await manager.initialize()
    return manager
