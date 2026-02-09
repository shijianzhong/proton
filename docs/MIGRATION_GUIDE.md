# 配置持久化迁移指南

## 快速开始

### 对于新用户

无需任何操作！直接使用即可：

```bash
# 1. 启动应用
python -m src.api.main

# 2. 通过 UI 或 API 配置服务
# 3. 配置会自动保存，重启后自动恢复
```

### 对于现有用户

如果你已经在使用环境变量配置，也无需迁移：

```bash
# 现有的环境变量仍然有效
export SMTP_USER="myemail@gmail.com"
export SMTP_PASSWORD="app_password"
export OPENAI_API_KEY="sk-xxxxx"

# 启动应用
python -m src.api.main

# 首次运行会使用环境变量
# 通过 UI 更新配置后，会自动保存到数据库
# 后续重启自动从数据库加载
```

---

## 配置优先级

```
数据库配置 > 环境变量 > 配置文件 > 默认值
```

### 示例

假设你配置了 SMTP：

1. **初始状态**（使用环境变量）:
   ```bash
   export SMTP_HOST="smtp.gmail.com"
   export SMTP_USER="user@gmail.com"
   ```

2. **通过 UI 修改为 QQ 邮箱**：
   - UI 更新 → API 保存 → 数据库存储
   - 配置立即生效

3. **重启应用**：
   - 从数据库加载 QQ 邮箱配置
   - 忽略环境变量中的 Gmail 配置

4. **删除数据库配置**：
   ```bash
   sqlite3 data/proton.db
   > DELETE FROM items WHERE collection='configs' AND id='email';
   ```
   - 重启后自动降级到环境变量配置

---

## 存储位置

### 默认存储（SQLite）

```
proton/
├── data/
│   └── proton.db          # 所有配置存储在此
└── ...
```

### PostgreSQL 存储

```bash
# 设置环境变量
export PROTON_STORAGE_TYPE="postgres"
export PROTON_POSTGRES_URL="postgresql://user:password@host:5432/proton"

# 启动应用
python -m src.api.main
```

### 文件存储（开发模式）

```bash
# 设置环境变量
export PROTON_STORAGE_TYPE="file"
export PROTON_STORAGE_PATH="./data"

# 配置文件位置
# ./data/configs/email.json
# ./data/configs/search.json
# ./data/configs/copilot.json
```

---

## 常见问题

### Q: 我的环境变量还能用吗？

**A**: 能用！环境变量作为 fallback，在数据库中没有配置时生效。

### Q: 如何备份配置？

**A**: 备份数据库文件：

```bash
# SQLite
cp data/proton.db data/proton.db.backup

# PostgreSQL
pg_dump proton > backup.sql
```

### Q: 如何重置配置？

**A**: 删除数据库中的配置记录：

```bash
sqlite3 data/proton.db
> DELETE FROM items WHERE collection='configs';
> .quit
```

或直接删除数据库文件：
```bash
rm data/proton.db
```

### Q: 配置存储在哪里？

**A**:
- **后端配置**（API Keys、密码）: 数据库
- **前端状态**（标签页选择）: 浏览器 localStorage

### Q: 配置是加密的吗？

**A**: 当前版本不加密。建议：
- 生产环境使用 PostgreSQL + 数据库加密
- 限制数据库访问权限
- 使用 HTTPS 访问 API

---

## 故障恢复

### 场景 1: 配置丢失

```bash
# 检查数据库
sqlite3 data/proton.db
> SELECT * FROM items WHERE collection='configs';

# 如果为空，配置会自动降级到环境变量
```

### 场景 2: 配置损坏

```bash
# 删除损坏的配置
sqlite3 data/proton.db
> DELETE FROM items WHERE collection='configs' AND id='email';

# 重启应用，使用环境变量
```

### 场景 3: 数据库错误

```bash
# 重建数据库
rm data/proton.db
python -m src.api.main

# 重新配置
```

---

## 最佳实践

### 开发环境

```bash
# 使用 SQLite（默认）
python -m src.api.main

# 配置通过 UI 管理
# 不提交 data/proton.db 到版本控制
```

### 生产环境

```bash
# 使用 PostgreSQL
export PROTON_STORAGE_TYPE="postgres"
export PROTON_POSTGRES_URL="postgresql://..."

# 定期备份数据库
# 配置数据库访问权限
# 使用 HTTPS
```

---

## 需要帮助？

查看完整文档: [CONFIG_PERSISTENCE.md](./CONFIG_PERSISTENCE.md)
