==================
InfoHub LLM 增强
==================

桥接本仓库既有的 ``llm`` 模块，为条目提供三种增强，都按源逐个开关，**默认全关**。

调用 ``llm`` 模块的两个反直觉之处
=================================

本仓库此前**没有任何摘要类的 LLM 调用**（唯一的 ``chat()`` 调用方是
``llm_assistant``，走的是有历史的会话），所以本模块建立了一次性提问的惯用法。
封装在 ``llm_client.py``，两个坑：

1. **``chat(messages, ...)`` 的 ``messages`` 要的是 ``mail.message`` 记录集，不是
   dict 列表。** 一次性提问的正确姿势是传一个**空记录集**，把 system/user 两轮放进
   ``prepend_messages``。参照 ``llm.provider._test_chat_model``。

   .. code-block:: python

       response = model.sudo().chat(
           env["mail.message"],          # 空记录集，无历史
           stream=False,
           prepend_messages=[
               {"role": "system", "content": system_prompt},
               {"role": "user", "content": content},
           ],
           max_tokens=512,
       )

2. **解析失败不抛异常，而是在返回的 dict 里给 ``error`` 键。** 所以既要
   ``try/except``，又要检查 ``response.get("error")``——只做一个会漏掉一半失败。

另外 ``llm`` 模块**没有任何超时设置**，SDK 默认可能长达数百秒。``llm_client`` 显式传
``timeout``，避免一个卡住的调用把 worker 占满。

所有失败形态（``UserError`` / ``NotImplementedError`` / ``ValueError`` / SDK 原生异常
/ ``error`` 键）统一收敛成 ``LlmCallFailed``，调用方只需处理一种。

原始内容不被覆盖
================

LLM 产出写在独立字段（``llm_summary`` / ``llm_translated_title`` /
``llm_translated_summary``），**不覆盖** ``summary`` 与 ``title``。

理由：模型会出错、会改口径。覆盖原文就没法回退、没法对比、没法在换模型后重新评估。
前端可以在有 LLM 摘要时优先展示它，但原文始终在。

成本控制
========

LLM 调用按量计费，所以有多层闸门：

* 三个开关按源独立，**默认全关**——装上模块不等于同意为每条内容付费
* ``llm_state`` 记录处理结果，成功或失败的条目不会反复重试
* 单次任务批量上限 20 条
* 输入截断到 12000 字符（摘要不需要全文）
* 正文短于 400 字符不做摘要（压缩没意义）
* 翻译只做标题与摘要，**不做全文**——成本高一个数量级，而读者主要靠标题决定要不要点开
* 翻译摘要时优先用本轮生成的 LLM 摘要而非原摘要（更短更省）

一个每天 200 条的源开启摘要就是每天 200 次调用。源表单上有对应提示。

零样本归类：只在没有受控分类码时才值得开
========================================

arXiv 这类有 ``cs.LG`` 精确编码的来源应该用 ``infohub_arxiv`` 的映射表 classifier
——那个既准又免费。本模块的 classifier 面向 RSS、网页这类只有自由文本分类（或完全没有
分类）的来源。

两者可以共存（``classifier`` 是用 ``many_components`` 取的，都会跑），所以本模块的
classifier 只在源上显式勾了 ``llm_classify`` 时才匹配。

事后校验是必需的，不是可选的
----------------------------

``llm`` 模块没有 JSON mode / ``response_format`` 的封装（kwargs 虽能透传到 SDK，
但那是 provider 特有、本仓库未验证的路径）。所以用**提示约束 + 事后校验**：把候选
学科编码列进提示，要求只回一个编码，拿到结果后**必须**在候选集里查得到才采用。

模型返回不存在的编码、多个编码、带解释的整句话都很常见。测试里覆盖了这几种：
"我认为这属于 technology 这个学科" 能提取出编码；``quantum-astrology`` 这种编造的
编码被拒绝。

候选集只用层级浅的学科（上限 40 个）让模型做粗分：全量 161 个会把提示撑得很长、
准确率反而下降。精分留给映射表或人工。

与 ``infohub_fulltext`` 的顺序
==============================

两者都是 enricher，执行顺序不保证。它们不冲突（正文提取写 ``content``，本模块读
``content_text`` 写 ``llm_*``），但顺序影响**质量**：先做正文提取再做摘要，摘要能看到
全文；反过来只能看到 RSS 给的一两句。

同时启用两者的源要接受"首轮摘要质量偏低、手工重试后变好"，或者只对已提取正文的条目
开摘要。

测试
====

见 ``.kiro/specs/infohub/stage7_test.py`` 第 4–6 节（40 项）：一次性提问的调用姿势
（断言传的是空 ``mail.message`` 记录集）、两条失败路径、输入截断、摘要与翻译、成本
闸门、零样本归类的事后校验。**全部 LLM 调用被 mock，不产生真实费用。**
