# SkillHub — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 数据模型、授权、上传/下载流、被否决方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线：

1. **压缩包当 blob**：不解析/校验 zip 内容（SKILL.md 结构），只存 blob + 元数据。
2. **字节流不过 MCP 通道**：上传/下载复用 storage_backend_mcp 的 URL broker（presign / relay）。
3. **授权双层**：技能级 record rules（owner/shared/public）+ 后端级 mcp_read_enabled。
4. **只按名字/描述搜索**：不加 tags。
