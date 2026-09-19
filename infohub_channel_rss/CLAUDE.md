# InfoHub RSS Channel — 开发约束（自动加载）

设计文档见 `docs/`，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 解析设计、SSRF 处理、被否决方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线：

1. **解析保持通用**，禁止为单个发布方写 `if` 分支；发布方私有字段原样保留进
   `raw_data` 供过滤。
2. **出网走 core 的 `url_guard`**，手工逐跳重定向，禁止 `allow_redirects=True`。
3. 本 addon 只贡献 `rss` 这一个渠道类型，配置字段加在自己 `_inherit` 上，
   不进 core。
