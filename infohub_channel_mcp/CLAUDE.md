# InfoHub MCP Channel — 开发约束（自动加载）

设计文档见 `docs/`，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 归一化、依赖隔离、被否决方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线：

1. **`llm` 依赖只在本 addon**，core `infohub` 不得因此改动、不得依赖 `llm`。
2. **工具返回做防御式归一化**，未知形状退化为空，禁止假设固定 schema。
3. 凭证不复制——端点/API key 只在 `llm.mcp.client` 上。
