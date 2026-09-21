===========
 LLM Discuss
===========

把 ``llm.agent`` 接到 Odoo 原生 Discuss，让 agent 以 bot 身份自动回复内部用户消息；
用户发来的图片 / PDF / 文本文件也会被 agent 读到。

工作方式
========

- **专用 bot 用户**：为 agent 建一个内部技术用户（``res.users``），在 Discuss 私聊 /
  群聊 / 悬浮 ChatWindow 里以 bot 身份回复；systray 提供 AI Agent 启动器。
- **OdooBot 私聊接管**：一个 agent 可接管用户已有的 OdooBot 私聊（原生 onboarding
  完成后），回复仍以 OdooBot 身份显示。
- **触发规则**：私聊、``@mention`` 或两者（agent 的 Reply Trigger）。
- **异步执行**：cron 驱动的栅栏队列 + 原生 typing 指示，生成完发一条完整回复。
- **页面上下文**：发消息时捕获当前后端页（记录 / 视图），供 agent 参考。
- **附件**：图片（JPEG/PNG/GIF/WebP）、PDF、文本文件进入 LLM 上下文；视频 / Office /
  音频会给出「不支持」提示（不静默）。

安装
====

- 依赖：``base`` + ``mail`` + ``mail_bot`` + ``llm``。
- 无新增 Python 依赖。

配置
====

1. 安装后到 LLM 后台为 agent 配置 **Enable in Discuss** 与 **Reply Trigger**，
   并创建 Bot User；或启用 **Use for OdooBot Private Chat**（全局仅一个）。
2. 把 bot 用户加进目标 chat / channel；网页 Live Chat 客服另装
   ``llm_discuss_livechat``。
3. 图片 / PDF 理解要求 agent 绑定 ``supports_image_input`` 的多模态模型。

安全
====

回复人格（bot / OdooBot）与执行身份分离：隐藏线程、记录读取、工具调用都以发送者
权限执行，provider 凭据与最终发帖用窄 sudo。附件读取在发送者 / bot 身份下进行，
绝不 sudo。

详细设计见 ``docs/``。
