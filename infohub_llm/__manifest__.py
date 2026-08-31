{
    "name": "InfoHub LLM 增强",
    "summary": "用 LLM 为条目生成摘要、翻译标题与摘要、零样本学科归类",
    "description": """
InfoHub LLM 增强
================
桥接本仓库既有的 ``llm`` 模块，为条目提供三种增强，都按源逐个开关：

* **摘要** —— 把长正文压成几句话
* **翻译** —— 把标题与摘要译成读者的语言
* **学科归类** —— 零样本分类，用于没有受控分类码的来源（RSS、网页）

原始内容不被覆盖
----------------
LLM 产出写在独立字段（``llm_summary`` / ``llm_translated_title`` / ...），不覆盖
``summary`` 与 ``title``。理由：LLM 会出错、会改口径，覆盖原文就没法回退，也没法
对比。前端可以在有 LLM 摘要时优先展示它。

成本控制
--------
LLM 调用要花钱，所以有多层闸门：

* 按源开关，默认全关
* ``llm_state`` 记录处理结果，成功或失败的条目不会反复重试
* 单次任务批量上限
* 输入文本截断（摘要不需要全文）
* 显式超时（``llm`` 模块自身不设超时，SDK 默认可能长达数百秒）

零样本归类的边界
----------------
只在**没有受控分类码**时才值得用。arXiv 这类有 ``cs.LG`` 精确编码的来源应该用
``infohub_arxiv`` 的映射表 classifier，那个既准又免费。本模块的 classifier 声明了
较低的适用范围，两者可以共存（``classifier`` 是用 ``many_components`` 取的）。
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Productivity",
    "version": "19.0.1.0.0",
    "depends": ["infohub", "llm"],
    "data": [
        "views/infohub_source_views.xml",
        "views/infohub_item_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
