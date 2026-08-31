"""调用 llm 模块的薄封装。

**这个仓库里还没有任何摘要类的 LLM 调用**，所以本文件建立惯用法。它刻意做成普通
Python 函数而不是 component：多个 component（enricher、classifier）都要用它，做成
函数比让它们多继承一个抽象 component 更简单、也更好测。

关于 llm 模块 API 的两个反直觉之处
----------------------------------
1. **``chat(messages, ...)`` 的 ``messages`` 要的是 ``mail.message`` 记录集，不是
   dict 列表。** 一次性提问（无历史）的正确姿势是传一个**空记录集**，把 system/user
   两轮放进 ``prepend_messages``。这是 ``llm.provider._test_chat_model`` 的做法，
   也是目前仓库里唯一的一次性提问先例。

2. **解析失败不抛异常，而是在返回的 dict 里给 ``error`` 键。** 所以既要
   ``try/except``，又要检查 ``response.get("error")``——只做一个会漏。

另外 llm 模块**没有任何超时设置**，SDK 默认可能长达数百秒。这里显式传 ``timeout``
（OpenAI SDK 支持按请求覆盖），避免一个卡住的调用把 worker 占满。
"""

import logging

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

#: 单次调用的超时（秒）。llm 模块自身不设超时，SDK 默认可能长达数百秒
DEFAULT_TIMEOUT = 90

#: 发给模型的文本长度上限。摘要不需要全文，截断能显著省钱且避免超上下文窗口
DEFAULT_MAX_INPUT_CHARS = 12_000


class LlmCallFailed(Exception):
    """LLM 调用失败。

    llm 模块没有自己的异常类型，失败形态五花八门（UserError、NotImplementedError、
    ValueError、SDK 原生异常，以及藏在返回值里的 error 键）。统一收敂成这一个，
    调用方就只需要处理一种。
    """


def resolve_model(env, model=None, model_use="chat"):
    """确定要用哪个 ``llm.model``。

    优先级：显式传入 → 全局默认（``is_default``）→ 任意可用的 chat 模型。

    llm 模块没有 ``ir.config_parameter`` 形式的全局默认，所以这里复用
    ``llm_assistant`` 的查找惯用法。
    """
    if model:
        return model

    Model = env["llm.model"].sudo()
    default = Model.search(
        [
            ("model_use", "in", ["chat", "multimodal"]),
            ("is_default", "=", True),
            ("active", "=", True),
        ],
        limit=1,
    )
    if default:
        return default

    fallback = Model.search(
        [("model_use", "in", ["chat", "multimodal"]), ("active", "=", True)], limit=1
    )
    if fallback:
        return fallback

    raise UserError(
        _("没有可用的 LLM 对话模型。请先在「LLM」里配置一个提供方与模型。")
    )


def chat(model, system_prompt, user_content, max_tokens=512, timeout=DEFAULT_TIMEOUT,
         max_input_chars=DEFAULT_MAX_INPUT_CHARS, **kwargs):
    """一次性提问，返回模型输出的纯文本。

    :param model: ``llm.model`` 记录
    :param str system_prompt: 系统提示
    :param str user_content: 用户内容，超长会被截断
    :param int max_tokens: 输出上限
    :param int timeout: 请求超时（秒）
    :return: 模型输出的文本，去除首尾空白
    :raise LlmCallFailed: 调用失败，或返回值里带 error
    """
    if not user_content or not user_content.strip():
        raise LlmCallFailed("输入内容为空。")

    content = user_content.strip()
    if max_input_chars and len(content) > max_input_chars:
        content = content[:max_input_chars]

    env = model.env
    try:
        response = model.sudo().chat(
            # 空记录集 + prepend_messages 是"一次性提问"的正确姿势，见模块文档
            env["mail.message"],
            stream=False,
            prepend_messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            max_tokens=max_tokens,
            timeout=timeout,
            **kwargs,
        )
    except Exception as exc:  # noqa: BLE001 - 见模块文档：失败形态五花八门
        raise LlmCallFailed(f"{type(exc).__name__}: {exc}") from exc

    if not isinstance(response, dict):
        raise LlmCallFailed(f"预期 dict 返回值，得到 {type(response).__name__}")

    # 解析失败不抛异常而是塞在 error 键里，必须显式检查
    if response.get("error"):
        raise LlmCallFailed(str(response["error"]))

    raw = response.get("content") or ""
    try:
        # content 可能是多段形式 [{"type": "text", "text": ...}]，
        # provider 上的这个方法会统一成字符串
        text = model.provider_id.sudo()._extract_content_text(raw)
    except Exception:  # noqa: BLE001 - 兜底：直接当字符串用
        text = raw if isinstance(raw, str) else str(raw)

    text = (text or "").strip()
    if not text:
        raise LlmCallFailed("模型返回了空内容。")
    return text
