# 配置持久化实现文档

## 概述

为解决页面刷新后配置数据丢失的问题，本次更新为 Proton 项目添加了完整的配置持久化方案。

## 实现方案

### 后端持久化（数据库）

对于包含敏感信息的配置（API Keys、密码等），使用数据库存储：

1. **邮件服务配置** (`EmailConfig`)
2. **搜索服务配置** (`SearchConfig`)
3. **模型服务配置** (`CopilotService`)

### 前端持久化（localStorage）

对于纯 UI 状态，使用浏览器 localStorage：

1. **设置面板当前标签页** (`proton_settings_active_tab`)

---

## 技术实现

### 1. 存储层扩展

#### 文件: `src/storage/persistence.py`

**新增配置集合常量**:
```python
class StorageManager:
    WORKFLOWS = "workflows"
    TEMPLATES = "templates"
    PLUGINS = "plugins"
    AGENTS = "agents"
    CONFIGS = "configs"  # 新增：全局配置存储
```

**新增配置 CRUD 方法**:
```python
async def save_config(config_type: str, config_data: Dict[str, Any]) -> None
async def load_config(config_type: str) -> Optional[Dict[str, Any]]
async def delete_config(config_type: str) -> bool
async def list_configs() -> List[Dict[str, Any]]
```

**支持的 config_type**:
- `"email"` - 邮件服务配置
- `"search"` - 搜索服务配置
- `"copilot"` - Copilot 配置

---

### 2. 邮件配置持久化

#### 文件: `src/tools/email.py`

**修改内容**:

1. **添加初始化方法**:
```python
@classmethod
async def initialize_from_storage(cls) -> "EmailConfig":
    """从数据库加载配置，失败则使用环境变量"""
    instance = cls.get_instance()

    if cls._initialized:
        return instance

    try:
        from ..storage.persistence import get_storage_manager
        storage = get_storage_manager()
        await storage.initialize()

        saved_config = await storage.load_config("email")

        if saved_config:
            logger.info("Loading email config from database")
            # 加载各字段...
        else:
            logger.info("No saved email config found, using environment variables")
    except Exception as e:
        logger.warning(f"Failed to load email config from storage: {e}")

    cls._initialized = True
    return instance
```

2. **添加保存方法**:
```python
async def save_to_storage(self) -> None:
    """保存当前配置到数据库"""
    try:
        from ..storage.persistence import get_storage_manager
        storage = get_storage_manager()
        await storage.initialize()

        config_data = {
            "resend_api_key": self.resend_api_key,
            "resend_from": self.resend_from,
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            # ... 其他字段
        }

        await storage.save_config("email", config_data)
        logger.info("Email config saved to database")
    except Exception as e:
        logger.error(f"Failed to save email config to storage: {e}")
```

3. **修改 update 方法为异步**:
```python
async def update(
    self,
    resend_api_key: Optional[str] = None,
    # ... 其他参数
) -> None:
    """更新配置并保存到数据库"""
    # 更新字段...

    # 保存到数据库
    await self.save_to_storage()
```

---

### 3. 搜索配置持久化

#### 文件: `src/tools/web.py`

**修改内容**（与邮件配置类似）:

1. 添加 `initialize_from_storage()` 类方法
2. 添加 `save_to_storage()` 实例方法
3. 修改 `update()` 为异步方法，调用 `save_to_storage()`

**配置字段**:
```python
{
    "provider": str,           # 当前搜索提供商
    "searxng_base_url": str,   # SearXNG 实例地址
    "serper_api_key": str,     # Serper API Key
    "brave_api_key": str,      # Brave Search API Key
    "bing_api_key": str,       # Bing API Key
    "google_api_key": str,     # Google API Key
    "google_cx": str,          # Google Custom Search CX
}
```

---

### 4. Copilot 配置持久化

#### 文件: `src/copilot/service.py`

**修改内容**:

1. **修改 update_config 为异步**:
```python
async def update_config(
    self,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> None:
    """更新配置并保存到数据库"""
    # 更新逻辑...

    # 保存到数据库
    await self.save_to_storage()
```

2. **添加保存方法**:
```python
async def save_to_storage(self) -> None:
    """保存当前配置到数据库"""
    try:
        from ..storage.persistence import get_storage_manager
        storage = get_storage_manager()
        await storage.initialize()

        config_data = {
            "provider": self.provider,
            "model": self.model,
            "api_key": self._api_key,
            "base_url": self._base_url,
        }

        await storage.save_config("copilot", config_data)
        logger.info("Copilot config saved to database")
    except Exception as e:
        logger.error(f"Failed to save copilot config to storage: {e}")
```

3. **添加加载方法**:
```python
async def load_from_storage(self) -> None:
    """从数据库加载配置"""
    try:
        from ..storage.persistence import get_storage_manager
        storage = get_storage_manager()
        await storage.initialize()

        saved_config = await storage.load_config("copilot")

        if saved_config:
            logger.info("Loading copilot config from database")
            self.provider = saved_config.get("provider", self.provider)
            self.model = saved_config.get("model", self.model)
            self._api_key = saved_config.get("api_key", self._api_key)
            self._base_url = saved_config.get("base_url", self._base_url)
            # 重置客户端以使用新配置
            self._client = None
        else:
            logger.info("No saved copilot config found")
    except Exception as e:
        logger.warning(f"Failed to load copilot config from storage: {e}")
```

---

### 5. API 端点更新

#### 文件: `src/api/main.py`

**修改后的端点（全部改为 await 调用）**:

```python
# Copilot 配置
@app.post("/api/copilot/config")
async def update_copilot_config(request: CopilotConfigRequest):
    from ..copilot import get_copilot_service
    copilot = get_copilot_service()
    await copilot.update_config(  # 改为 await
        provider=request.provider,
        model=request.model,
        api_key=request.api_key,
        base_url=request.base_url,
    )
    return {
        "status": "updated",
        "config": copilot.get_config(),
    }

# 搜索配置
@app.post("/api/search/config")
async def update_search_config(request: SearchConfigRequest):
    from ..tools import get_search_config
    config = get_search_config()
    await config.update(  # 改为 await
        provider=request.provider,
        # ... 其他参数
    )
    return {
        "status": "updated",
        "config": config.to_dict(),
    }

# 邮件配置
@app.post("/api/email/config")
async def update_email_config(request: EmailConfigRequest):
    try:
        from ..tools.email import get_email_config
        config = get_email_config()
        await config.update(  # 改为 await
            preferred_method=request.preferred_method,
            # ... 其他参数
        )
        return {
            "status": "updated",
            "config": config.to_dict(),
        }
    except ImportError:
        raise HTTPException(...)
```

---

### 6. 应用启动时加载配置

#### 文件: `src/api/main.py`

**在 lifespan 函数中添加配置加载**:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Proton Agent Platform...")

    # Initialize storage
    from ..storage import initialize_storage
    storage = await initialize_storage()
    logger.info("Storage initialized")

    # 加载配置
    logger.info("Loading configurations from database...")
    try:
        from ..tools.email import EmailConfig
        from ..tools.web import SearchConfig
        from ..copilot import get_copilot_service

        # 初始化邮件配置
        await EmailConfig.initialize_from_storage()
        logger.info("Email configuration loaded")

        # 初始化搜索配置
        await SearchConfig.initialize_from_storage()
        logger.info("Search configuration loaded")

        # 初始化 Copilot 配置
        copilot = get_copilot_service()
        await copilot.load_from_storage()
        logger.info("Copilot configuration loaded")
    except Exception as e:
        logger.warning(f"Failed to load some configurations: {e}")

    # Pre-load workflows
    manager = get_workflow_manager()
    await manager._ensure_storage()

    yield

    # Shutdown
    logger.info("Shutting down Proton Agent Platform...")
    # ... 清理逻辑
```

**配置加载优先级**:
1. 数据库中的配置（如果存在）
2. 环境变量（fallback）

---

### 7. 前端 localStorage 支持

#### 文件: `ui/src/components/SettingsPanel.tsx`

**修改内容**:

1. **从 localStorage 恢复标签页状态**:
```typescript
const [activeTab, setActiveTab] = useState<TabType>(() => {
  const saved = localStorage.getItem('proton_settings_active_tab');
  return (saved as TabType) || 'search';
});
```

2. **监听标签页变化并保存**:
```typescript
useEffect(() => {
  localStorage.setItem('proton_settings_active_tab', activeTab);
}, [activeTab]);
```

---

## 配置存储位置

### 数据库位置

根据 `PROTON_STORAGE_TYPE` 环境变量：

| 存储类型 | 位置 | 环境变量 |
|---------|------|---------|
| SQLite (默认) | `./data/proton.db` | `PROTON_SQLITE_PATH` |
| PostgreSQL | 远程数据库 | `PROTON_POSTGRES_URL` |
| File (开发) | `./data/configs/` | `PROTON_STORAGE_PATH` |

**表结构** (SQLite/PostgreSQL):
```sql
CREATE TABLE items (
    collection TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT/JSONB NOT NULL,
    created_at TEXT/TIMESTAMPTZ NOT NULL,
    updated_at TEXT/TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (collection, id)
);
```

**配置记录示例**:
```json
{
  "collection": "configs",
  "id": "email",
  "data": {
    "resend_api_key": "re_xxxxx",
    "resend_from": "noreply@example.com",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "user@gmail.com",
    "smtp_password": "app_password",
    "smtp_from": "",
    "smtp_use_tls": true,
    "preferred_method": "auto"
  },
  "created_at": "2024-01-15T10:30:00",
  "updated_at": "2024-01-15T14:20:00"
}
```

### localStorage 位置

浏览器 localStorage，key 为 `proton_settings_active_tab`。

---

## 使用示例

### 场景 1: 配置邮件服务

```bash
# 1. 通过 API 配置
curl -X POST http://localhost:8000/api/email/config \
  -H "Content-Type: application/json" \
  -d '{
    "preferred_method": "smtp",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "myemail@gmail.com",
    "smtp_password": "app_password",
    "smtp_use_tls": true
  }'

# 2. 配置会自动保存到数据库

# 3. 重启应用后配置自动加载
python -m src.api.main

# 4. 验证配置已加载
curl http://localhost:8000/api/email/config
```

### 场景 2: 配置 Copilot

```bash
# 1. 配置 Copilot 使用 Zhipu GLM-4
curl -X POST http://localhost:8000/api/copilot/config \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "zhipu",
    "model": "glm-4",
    "api_key": "your_zhipu_api_key"
  }'

# 2. 重启后自动恢复
# 3. 可通过 UI 设置面板验证
```

### 场景 3: 前端标签页恢复

```typescript
// 1. 用户打开设置面板，切换到 Copilot 标签页
// 2. 刷新页面
// 3. 再次打开设置面板时，仍然在 Copilot 标签页
```

---

## 测试清单

### 后端测试

- [ ] 启动应用，配置三个服务（Email、Search、Copilot）
- [ ] 重启应用，验证配置已恢复
- [ ] 修改配置，验证立即生效
- [ ] 删除数据库文件，验证自动降级到环境变量
- [ ] 测试 SQLite、PostgreSQL、File 三种存储后端

### 前端测试

- [ ] 打开设置面板，切换标签页
- [ ] 刷新页面，验证标签页状态保持
- [ ] 关闭浏览器，重新打开，验证状态保持
- [ ] 清除 localStorage，验证降级到默认标签页

---

## 兼容性说明

### 向后兼容

1. **环境变量仍然有效**：如果数据库中没有配置，会自动使用环境变量
2. **配置文件仍然有效**：Copilot 配置仍然支持 `config/default.yaml`
3. **优先级**：数据库 > 环境变量 > 配置文件 > 默认值

### 迁移路径

从旧版本升级：
1. 无需迁移，自动兼容
2. 首次运行时使用环境变量
3. 通过 UI 或 API 更新配置后，会自动保存到数据库
4. 后续重启自动从数据库加载

---

## 安全性考虑

### 敏感信息保护

1. **数据库存储**：
   - API Keys 和密码存储在数据库中（明文）
   - 生产环境应使用 PostgreSQL 并配置访问控制
   - 建议使用云数据库的加密功能

2. **API 响应**：
   - 所有配置 API 端点都会 mask 敏感信息
   - 例如：`re_xxxxx` → `re_x****xxxxx`

3. **日志**：
   - 日志中不输出完整 API Key
   - 仅显示 "configured" 或 "NOT SET"

### 推荐实践

1. **生产环境**：
   - 使用 PostgreSQL 存储配置
   - 配置数据库访问权限
   - 使用 HTTPS 访问 API
   - 定期备份数据库

2. **开发环境**：
   - 使用 SQLite (默认)
   - 不提交 `.db` 文件到版本控制
   - 使用 `.env` 文件管理环境变量

---

## 故障排查

### 配置未保存

**症状**：配置更新后重启丢失

**检查**：
```bash
# 1. 查看日志
tail -f logs/proton.log | grep "config"

# 2. 检查数据库
sqlite3 data/proton.db
> SELECT * FROM items WHERE collection='configs';

# 3. 检查存储类型
echo $PROTON_STORAGE_TYPE
```

### 配置加载失败

**症状**：启动时警告 "Failed to load config"

**原因**：
- 数据库权限问题
- 数据格式错误
- 网络问题（PostgreSQL）

**解决**：
```bash
# 删除损坏的配置
sqlite3 data/proton.db
> DELETE FROM items WHERE collection='configs' AND id='email';

# 重启应用，使用环境变量
```

---

## 未来改进

1. **配置加密**：对 API Keys 和密码进行加密存储
2. **配置版本管理**：支持配置回滚
3. **配置导入导出**：支持配置备份和迁移
4. **UI 配置管理**：在 UI 中显示配置历史
5. **配置验证**：保存前验证配置有效性

---

## 相关文件

### 后端文件
- `src/storage/persistence.py` - 存储管理器
- `src/tools/email.py` - 邮件配置
- `src/tools/web.py` - 搜索配置
- `src/copilot/service.py` - Copilot 配置
- `src/api/main.py` - API 端点

### 前端文件
- `ui/src/components/SettingsPanel.tsx` - 设置面板
- `ui/src/api/client.ts` - API 客户端

---

## 总结

本次更新通过以下方式解决了配置持久化问题：

1. ✅ **数据库持久化**：敏感配置保存到数据库
2. ✅ **自动加载**：应用启动时自动恢复配置
3. ✅ **实时保存**：配置更新时立即保存
4. ✅ **前端状态**：UI 状态保存到 localStorage
5. ✅ **向后兼容**：支持环境变量和配置文件
6. ✅ **多存储后端**：支持 SQLite、PostgreSQL、File

用户现在可以放心配置服务，不必担心重启或刷新导致配置丢失。
