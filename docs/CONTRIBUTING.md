# 贡献规范

## 提交范围

- 仅提交源码、测试、文档与可复现配置。
- 避免提交本地缓存、运行日志、临时文件与环境产物。

## 运行期产物

- `data/skills/*` 属于运行期生成产物，不应提交到 Git。
- `data/skills/registry.json` 可按项目需要决定是否跟踪；当前仓库保留该文件路径为可选登记位。
- 自动生成的 `.skill` 包、`generated` 目录、按 UUID 产生的 skill 实例目录均应忽略。

## 提交前检查

- 后端改动执行 `pytest -q`。
- 前端改动执行 `npm test` 与 `npm run build`（在 `ui/` 目录）。
- 保证 `git status` 中不包含运行期产物与无关变更。

## 提交信息建议

- 使用清晰前缀：`feat`、`fix`、`refactor`、`test`、`docs`、`chore`。
- 一次提交聚焦一个主题，避免将功能改动与大量产物文件混在同一提交中。
