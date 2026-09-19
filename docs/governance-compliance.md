# 治理合规状态

> 依据 [`development-governance.md`](development-governance.md) 逐 addon 盘点。
> 规范是"**新 addon 强制、存量碰到就补**"（§5/§6），本表是追踪入口，不是立即
> 整改的军令状。改动某个 addon 时，把它销账到合规。

## 汇总

| 指标 | 现状 | 目标 |
|---|---|---|
| addon 总数 | 63 | — |
| README.rst | 24 | 63 |
| README.md（需转 .rst） | 17 | 0 |
| 无 README | 22 | 0 |
| docs/ 三件套齐全 | 0 | 63 |
| CLAUDE.md | 0 | 63 |
| tests/ | 36 | 63 |
| manifest 带 description（违反 §1） | 22 | 0 |
| manifest 不可解析 | 1 | 0 |

## 完全合规的 addon

暂无。（截至本次盘点）

## 各 addon 缺口

图例：✓ 已有 · 缺失；`desc` 指 manifest 带 description 键（§1 违规）。

| addon | README.rst | docs 三件套 | CLAUDE.md | tests | manifest description |
|---|---|---|---|---|---|
| async_task | · | · | · | · | ✓ |
| base_pgvector | · | · | · | · | desc |
| component | ✓ | · | · | ✓ | ✓ |
| component_event | ✓ | · | · | ✓ | ✓ |
| connector | ✓ | · | · | ✓ | ✓ |
| dataset | · | · | · | ✓ | desc |
| dataset_dataframe | · | · | · | · | desc |
| dataset_storage | · | · | · | ✓ | ✓ |
| infohub | ✓ | · | · | ✓ | desc |
| infohub_agent | ✓ | · | · | ✓ | desc |
| infohub_channel_biomedtracker | · | · | · | ✓ | desc |
| infohub_channel_email | · | · | · | ✓ | desc |
| infohub_channel_mcp | · | · | · | ✓ | desc |
| infohub_channel_rss | · | · | · | ✓ | desc |
| llm | · | · | · | ✓ | desc |
| llm_anthropic | · | · | · | ✓ | desc |
| llm_discuss | · | · | · | · | desc |
| llm_discuss_livechat | · | · | · | · | desc |
| llm_knowledge | · | · | · | ✓ | desc |
| llm_knowledge_automation | · | · | · | · | ✓ |
| llm_knowledge_extractor_markitdown | · | · | · | · | ✓ |
| llm_knowledge_extractor_mineru | · | · | · | · | ✓ |
| llm_knowledge_extractor_trafilatura | · | · | · | · | ✓ |
| llm_knowledge_pgvector | · | · | · | · | desc |
| llm_mcp_server | · | ✓(仅目录，非三件套) | · | ✓ | desc |
| llm_openai | · | · | · | ✓ | desc |
| llm_openai_compatible | · | · | · | ✓ | desc |
| llm_pg | · | · | · | · | ✓ |
| llm_pg_search | · | · | · | · | ✓ |
| llm_pg_textsearch | · | · | · | · | ✓ |
| llm_pgvector | · | · | · | ✓ | ✓ |
| llm_pgvectorscale | · | · | · | · | ✓ |
| llm_qdrant | · | · | · | · | desc |
| mail_environment | ✓ | · | · | ✓ | ✓ |
| one_cloud | · | · | · | · | ✓ |
| one_cloud_digitalocean | · | · | · | ✓ | ✓ |
| one_cloud_firewall | · | · | · | ✓ | ✓ |
| one_cloud_tencent | · | · | · | ✓ | ✓ |
| one_storage | ✓ | · | · | ✓ | ✓ |
| posters | · | · | · | · | ✓ |
| project_task_gantt | · | · | · | · | **不可解析** |
| queue_job | ✓ | · | · | ✓ | ✓ |
| queue_job_batch | ✓ | · | · | · | ✓ |
| queue_job_cron | ✓ | · | · | ✓ | ✓ |
| queue_job_cron_jobrunner | ✓ | · | · | ✓ | ✓ |
| queue_job_subscribe | ✓ | · | · | ✓ | ✓ |
| server_environment | ✓ | · | · | ✓ | ✓ |
| server_environment_ir_config_parameter | ✓ | · | · | ✓ | ✓ |
| spreadsheet_dashboard_oca | ✓ | · | · | · | ✓ |
| spreadsheet_oca | ✓ | · | · | · | ✓ |
| storage_backend | ✓ | · | · | ✓ | ✓ |
| storage_backend_ftp | ✓ | · | · | ✓ | ✓ |
| storage_backend_s3 | ✓ | · | · | ✓ | ✓ |
| storage_backend_sftp | ✓ | · | · | ✓ | ✓ |
| storage_backend_sharepoint | ✓ | · | · | · | ✓ |
| web_color_selection | · | · | · | · | ✓ |
| web_company_color | ✓ | · | · | ✓ | ✓ |
| web_favicon | ✓ | · | · | ✓ | ✓ |
| web_gantt | · | · | · | · | desc |
| web_json_editor | · | · | · | · | desc |
| web_responsive | ✓ | · | · | ✓ | ✓ |
| web_widget_mermaid | · | · | · | · | desc |
| wecom | · | · | · | · | ✓ |

## 备注

- **`.rst` 多为 OCA vendored**（component、connector、queue_job*、storage_backend*、
  web_*、server_environment*），它们遵循 OCA 的 README.rst 惯例。
- **`.md` 多为自研**（llm*、dataset*），需按 §1 转成 `.rst` 并拆出 docs/ 三件套。
- **`project_task_gantt`** 的 `__manifest__.py` 为 0 字节（自加入起就是），`__init__.py`
  也是空，属于半成品，需作者决定补全或删除。
- 本表在每次盘点后更新；"碰到就补"的 addon 改为 ✓ 时同步刷新。

## 盘点方式

用 `scripts/` 下尚未建立的一键脚本（待建）。当前为一次性内联扫描，输出见本文件。
