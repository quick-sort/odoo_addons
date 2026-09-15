"""LLM 增强 enricher：摘要 + 翻译。

用 ``many_components(usage='enricher')`` 被取到，所以本模块和 ``infohub_fulltext``
可以各挂一个、互不知晓。执行顺序不保证，但两者不冲突：正文提取写 ``content``，
本模块读 ``content_text`` 写 ``llm_*``。

不过顺序确实影响**质量**：先做正文提取再做摘要，摘要能看到全文；反过来只能看到
RSS 给的一两句。这一点写在 README 里，建议同时启用两者的源接受"首轮摘要质量偏低、
手工重试后变好"，或只对已提取正文的条目开摘要。
"""

import logging

from odoo.addons.component.core import Component
from odoo.tools import html2plaintext

from ..llm_client import LlmCallFailed, chat, resolve_model

_logger = logging.getLogger(__name__)

#: 单次任务最多处理多少条。LLM 调用慢且花钱，批量必须小
BATCH_LIMIT = 20

#: 正文短于这个长度就不值得让模型再压缩一遍
MIN_CONTENT_FOR_SUMMARY = 400

SUMMARY_PROMPT = (
    "你是一个信息摘要助手。请用 2-3 句话概括下面这段内容的核心信息，"
    "只输出摘要正文，不要加任何前缀、标题或解释。"
    "如果内容本身是中文就用中文回答，否则用内容原本的语言。"
)

TRANSLATE_PROMPT = (
    "你是一个翻译助手。请把下面的内容翻译成 %(lang)s，"
    "只输出译文，不要加任何前缀、解释或原文。"
    "保持原意与专业术语的准确性，不要意译或增删信息。"
)


class LlmEnricher(Component):
    _name = "infohub.enricher.llm"
    _inherit = "infohub.enricher.base"
    _provider = None
    _medium = None

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        source = cls._work_source(work)
        return bool(source) and source._llm_enabled()

    # ==================================================================
    def enrich(self, items):
        candidates = items.filtered(lambda item: item.llm_state == "pending")
        if not candidates:
            return True

        source = self.source
        try:
            model = resolve_model(self.env, source.llm_model_id)
        except Exception as exc:  # noqa: BLE001 - 没配模型时不该让整批增强炸掉
            _logger.warning(
                "InfoHub LLM：源 %s 无法确定模型，跳过本轮：%s",
                source.display_name,
                exc,
            )
            return False

        processed = 0
        for item in candidates[:BATCH_LIMIT]:
            self._process_one(item, model, source)
            processed += 1

        remaining = len(candidates) - processed
        if remaining > 0:
            _logger.info(
                "InfoHub LLM：源 %s 还有 %s 条待处理，留给下一轮",
                source.display_name,
                remaining,
            )
        return True

    def _process_one(self, item, model, source):
        """处理单条。任何失败只影响这一条。"""
        vals = {}
        errors = []
        summary_text = None

        if source.llm_summarize:
            summary_text, error = self._summarize(item, model)
            if summary_text:
                vals["llm_summary"] = summary_text
            elif error:
                errors.append(f"摘要：{error}")

        if source.llm_translate_to:
            # 把本轮刚算出的摘要传进去。不能让 _translate 自己去读
            # item.llm_summary——那还没写库（vals 是在最后一次性 write 的），
            # 读到的永远是空，"翻译更短的摘要"这个优化就静默失效了。
            translated, error = self._translate(
                item, model, source.llm_translate_to, summary_text=summary_text
            )
            if translated:
                vals.update(translated)
            elif error:
                errors.append(f"翻译：{error}")

        if errors and not vals:
            # 全都失败了才算失败；部分成功仍记为已处理，避免为了一半重跑另一半
            item.write({"llm_state": "failed", "llm_error": "\n".join(errors)})
            return False

        vals["llm_state"] = "done"
        vals["llm_error"] = "\n".join(errors) if errors else False
        item.write(vals)
        return True

    # ------------------------------------------------------------------
    def _source_text(self, item):
        """挑一段最适合喂给模型的文本。

        优先正文纯文本（信息最全），退回摘要（HTML，要先转纯文本），再退回标题。
        """
        if item.content_text and item.content_text.strip():
            return item.content_text.strip()
        if item.summary:
            text = (html2plaintext(item.summary) or "").strip()
            if text:
                return text
        if item.title and item.title.strip():
            return item.title.strip()
        return None

    def _summarize(self, item, model):
        text = self._source_text(item)
        if not text:
            return None, "没有可用的文本"
        if len(text) < MIN_CONTENT_FOR_SUMMARY:
            # 太短了，压缩没意义
            return None, None
        try:
            return chat(model, SUMMARY_PROMPT, text, max_tokens=400), None
        except LlmCallFailed as exc:
            _logger.info("InfoHub LLM：条目 %s 摘要失败：%s", item.id, exc)
            return None, str(exc)

    def _translate(self, item, model, target_lang, summary_text=None):
        """翻译标题与摘要。

        只译这两项：全文翻译成本高一个数量级，而读者主要靠标题决定要不要点开。

        :param summary_text: 本轮刚生成的 LLM 摘要。优先用它——比原摘要短，
            翻译更省；而且此时它还没写库，只能由调用方传进来。
        """
        prompt = TRANSLATE_PROMPT % {"lang": target_lang}
        result = {}
        errors = []

        if item.title:
            try:
                result["llm_translated_title"] = chat(
                    model, prompt, item.title, max_tokens=200
                )
            except LlmCallFailed as exc:
                errors.append(f"标题 {exc}")

        # 优先本轮的 LLM 摘要 → 已存在的 LLM 摘要 → 原摘要
        source_summary = summary_text or item.llm_summary
        if not source_summary and item.summary:
            source_summary = html2plaintext(item.summary)
        if source_summary and source_summary.strip():
            try:
                result["llm_translated_summary"] = chat(
                    model, prompt, source_summary, max_tokens=500
                )
            except LlmCallFailed as exc:
                errors.append(f"摘要 {exc}")

        if not result:
            return None, "; ".join(errors) or "没有可翻译的内容"
        return result, "; ".join(errors) if errors else None
