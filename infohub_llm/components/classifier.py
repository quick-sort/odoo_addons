"""零样本学科归类。

**只在来源没有受控分类码时才值得开。** arXiv 这类有 ``cs.LG`` 精确编码的来源应该用
``infohub_arxiv`` 的映射表 classifier——那个既准又免费。本 classifier 面向 RSS、网页
这类只有自由文本分类（或完全没有分类）的来源。

两者可以共存：``classifier`` 是用 ``many_components`` 取的，都会跑。所以本模块只在
源上显式勾了 ``llm_classify`` 时才生效。

输出约束的做法
--------------
llm 模块没有 JSON mode / response_format 的封装（虽然 kwargs 能透传到 SDK，但那是
provider 特有的、未经本仓库验证的路径）。所以这里用**提示约束 + 事后校验**：把候选
学科编码列进提示，要求只回一个编码，拿到结果后**必须**在候选集里查得到才采用。

模型返回不存在的编码、多个编码、或带解释的句子都很常见，事后校验是必需的而不是
可选的。
"""

import logging
import re

from odoo.addons.component.core import Component

from ..llm_client import LlmCallFailed, chat, resolve_model

_logger = logging.getLogger(__name__)

#: 送进提示的候选学科上限。全量 161 个会把提示撑得很长且降低准确率，
#: 所以只用一级学科（archive 层）让模型先粗分，精分交给人或规则
MAX_CANDIDATES = 40

#: 用于判断模型输出里是否含某个编码
CODE_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]*")

CLASSIFY_PROMPT = (
    "你是一个学科归类助手。下面给出候选学科列表（格式为 `编码 名称`），"
    "请判断随后的内容属于哪一个学科。\n\n"
    "候选学科：\n%(candidates)s\n\n"
    "要求：只输出一个编码，不要输出名称、解释或任何其他文字。"
    "如果都不合适，输出 NONE。"
)


class LlmClassifier(Component):
    _name = "infohub.classifier.llm"
    _inherit = "infohub.classifier.base"
    _provider = None
    _medium = None

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        source = cls._work_source(work)
        return bool(source) and source.llm_classify

    # ==================================================================
    def classify(self, item, entry):
        candidates = self._candidates()
        if not candidates:
            _logger.info("InfoHub LLM 归类：没有可用的候选学科，跳过")
            return False

        text = self._text(item)
        if not text:
            return False

        try:
            model = resolve_model(self.env, self.source.llm_model_id)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("InfoHub LLM 归类：无法确定模型，跳过：%s", exc)
            return False

        prompt = CLASSIFY_PROMPT % {
            "candidates": "\n".join(
                f"{topic.code} {topic.name}" for topic in candidates
            )
        }
        try:
            answer = chat(model, prompt, text, max_tokens=32)
        except LlmCallFailed as exc:
            _logger.info("InfoHub LLM 归类：条目 %s 失败：%s", item.id, exc)
            return False

        topic = self._match_answer(answer, candidates)
        if not topic:
            _logger.info(
                "InfoHub LLM 归类：条目 %s 的回答 %r 不在候选集里，忽略",
                item.id,
                answer[:60],
            )
            return False

        item.topic_ids = [(4, topic.id)]
        if not item.primary_topic_id:
            item.primary_topic_id = topic
        return True

    # ------------------------------------------------------------------
    def _candidates(self):
        """候选学科：有编码的顶层学科。

        只用一级（无父级或父级是根）让模型做粗分：全量 161 个会把提示撑得很长、
        准确率反而下降。精分留给映射表或人工。
        """
        Topic = self.env["infohub.topic"]
        topics = Topic.search(
            [("code", "!=", False), ("active", "=", True)],
            order="sequence, complete_name",
        )
        # 优先取层级浅的
        shallow = topics.filtered(lambda t: (t.parent_path or "").count("/") <= 2)
        return (shallow or topics)[:MAX_CANDIDATES]

    @staticmethod
    def _text(item):
        parts = [item.title or ""]
        if item.content_text:
            parts.append(item.content_text[:2000])
        text = "\n".join(p for p in parts if p).strip()
        return text or None

    @staticmethod
    def _match_answer(answer, candidates):
        """把模型输出对回候选集。

        **必须做这一步**：模型返回不存在的编码、多个编码、或带解释的句子都很常见。
        先试整串精确匹配（不区分大小写），再从输出里逐个 token 找。
        """
        cleaned = (answer or "").strip()
        if not cleaned or cleaned.upper() == "NONE":
            return None

        by_code = {topic.code.lower(): topic for topic in candidates if topic.code}

        exact = by_code.get(cleaned.lower())
        if exact:
            return exact

        for token in CODE_RE.findall(cleaned):
            found = by_code.get(token.lower())
            if found:
                return found
        return None
