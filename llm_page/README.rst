=========
 LLM Page
=========

让 agent（Claude Code / OpenClaw 等）生成的静态 HTML（含 JS）通过 Odoo website
对外 host，并受「指定用户组」授权 + 「三级审核」流程管控。

工作方式
========

- agent 经 ``storage_backend_mcp`` 暂存上传 HTML（``storage_stage_upload`` →
  curl 上传 → ``storage_commit_upload`` 得 ``file_id``），再调用
  ``llm_page_create(file_id)`` 登记为一个待审核页面。
- 页面正文以**原始 HTML** 存储（``fields.Text``，不 sanitize，``<script>`` /
  ``<style>`` 可运行），经 ``website.layout`` 主题包裹后渲染。
- 三级审核：``draft → pending → published``，另含 ``rejected`` 驳回与
  ``unpublish`` 下架。只有 ``LLM Page Reviewer`` 组能通过/驳回/下架。
- 授权访问：每页指定一个访问组（``group_id``），已发布页仅该组成员可访问；
  审核员可预览未发布页。

安装
====

- 依赖：``website`` + ``storage_backend_mcp``（后者带来 ``storage_backend``、
  ``llm``）。
- 无新增 Python 依赖。

配置
====

- 后台菜单 **LLM Pages**：审核员在表单上预览 / 通过 / 驳回 / 下架，
  并调整每页的访问组（``group_id``）。
- 访问组默认落在 ``LLM Page Viewer`` 组；agent 不能指定，需审核员在后台调整。

安全
====

- ``html`` 默认不净化以支持 JS，安全由「审核员放行 + 指定用户组访问」双闸门
  兜底。不要把访问组指向过宽的人群，除非已人工审查脚本内容。

详细设计见 ``docs/``。
