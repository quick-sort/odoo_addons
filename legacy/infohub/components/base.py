"""InfoHub 三轴 component 抽象基类。

信息源由三个正交维度组合定义（ADR-002）::

    infohub.source = medium × transport × provider

每个维度有一个抽象基类，各自只看自己那一维，**互不继承**。轴内继承（例如
期刊 mapper 继承通用 RSS mapper）是允许的；跨轴继承是设计错误。

关于声明方式
------------
每个类都写 ``class X(AbstractComponent)`` 加 ``_inherit = "父组件名"``，而**不是**
Python 类继承。component 框架用 ``_inherit`` 字符串建立注册表关系（见
``component/core.py`` 的 ``_build_component``），Python 继承不算数：靠 Python
继承虽然属性能通过 MRO 取到，但注册表链是断的，第三方模块用
``_inherit = "infohub.base"`` 追加的方法不会被子类继承。仓库里 ``connector``
的 component 也是这个写法。

关于唯一匹配（ADR-007）
-----------------------
``WorkContext.component()`` 匹配到多个候选时抛 ``SeveralComponentError``，
而它内置的消歧只按 collection 和 model（见 ``component/core.py`` 的
``_filter_components_by_collection`` / ``_filter_components_by_model``），在
三轴场景下都无法消歧。因此：

* ``provider`` 在 ``infohub.source`` 上是必填字段，默认 ``generic``
* mapper 的匹配键是 ``(provider, transport)``，保证每个源恰好命中一个

新增维度实现时，必须保证 ``_component_match`` 的结果在任一源上唯一。
"""

from odoo.addons.component.core import AbstractComponent


class InfohubBase(AbstractComponent):
    """所有 InfoHub component 的共同基类。

    提供 ``source`` 快捷属性。``infohub.source.work_on()`` 会把源记录注入
    WorkContext，所以任何 component 都能通过 ``self.source`` 拿到它。
    """

    _name = "infohub.base"
    _collection = "infohub.source"

    @property
    def source(self):
        """当前工作的 ``infohub.source`` 记录。"""
        return self.work.source

    @classmethod
    def _work_source(cls, work):
        """安全地取 WorkContext 上的源记录。

        没有源时返回 None 而不是抛 AttributeError，这样 ``_component_match``
        在非常规调用下只是不匹配，而不是让整个 lookup 崩掉。
        """
        return getattr(work, "source", None)


class TransportBase(AbstractComponent):
    """传输维度：怎么拿到字节、怎么做增量。

    子类须声明 ``_transport`` 并实现 :meth:`fetch`。

    实现约定：

    * 出网必须走 ``infohub.http`` component（SSRF 防护、超时、体积上限），
      不要直接调 ``requests``
    * 增量游标从 ``self.source.cursor_state`` 读，新游标由 :meth:`fetch` 返回，
      由调用方负责写回（失败时不写回，下次重试仍用旧游标）
    """

    _name = "infohub.transport.base"
    _inherit = "infohub.base"
    _usage = "transport"
    _transport = None

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        source = cls._work_source(work)
        return bool(source) and cls._transport == source.transport

    def fetch(self):
        """抓取原始条目。

        :return: ``(entries, cursor_state)``

            * ``entries``: 可迭代的原始条目，元素形态由传输自己定义，会原样
              传给 mapper
            * ``cursor_state``: dict，本轮结束后的新游标；返回 None 表示
              不更新游标
        """
        raise NotImplementedError


class MediumBase(AbstractComponent):
    """介质维度：条目的字段语义、扩展数据结构、**去重身份算法**。

    子类须声明 ``_medium``，通常还要声明 ``_payload_model``（介质载荷表的
    模型名，见 ``infohub.medium.payload``）。

    去重身份归属介质而非来源（ADR-006）：论文的身份是归一化 DOI，新闻的身份
    是 GUID 或规范化 URL。这样同一篇论文经 arXiv、期刊 RSS、Crossref 三路
    进入时能收敛为一条。
    """

    _name = "infohub.medium.base"
    _inherit = "infohub.base"
    _usage = "medium"
    _medium = None
    _payload_model = None

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        source = cls._work_source(work)
        return bool(source) and cls._medium == source.medium

    def identity(self, payload):
        """计算跨源去重身份。

        :param dict payload: mapper 产出的归一化数据
        :return: 字符串身份键；返回 None 表示该条目不参与跨源去重
        """
        raise NotImplementedError

    def payload_model(self):
        """返回介质载荷模型，未声明则返回 None。"""
        if not self._payload_model:
            return None
        return self.env[self._payload_model]

    def payload_vals(self, payload):
        """从归一化数据中提取介质载荷表的字段值。

        :param dict payload: mapper 产出的归一化数据
        :return: dict，载荷表的 vals（不含 ``item_id``）
        """
        return {}

    def store_payload(self, item, payload):
        """为条目创建或更新介质载荷记录。

        无 ``_payload_model`` 的介质（如 ``article``）默认无载荷表，直接返回。
        """
        model = self.payload_model()
        if model is None:
            return model
        vals = self.payload_vals(payload)
        existing = model.search([("item_id", "=", item.id)], limit=1)
        if existing:
            if vals:
                existing.write(vals)
            return existing
        return model.create(dict(vals, item_id=item.id))


class MapperBase(AbstractComponent):
    """来源维度：把原始条目映射成归一化数据。

    子类须声明 ``_provider``，可选声明 ``_transport``。

    ``_transport`` 为 None 表示该 mapper 不限传输；通用 mapper 应当同时声明
    两者，例如 ``infohub_rss`` 提供 ``(generic, rss)``、``infohub_web`` 提供
    ``(generic, web)``，这样它们互不冲突（ADR-007）。
    """

    _name = "infohub.mapper.base"
    _inherit = "infohub.base"
    _usage = "mapper"
    _provider = None
    _transport = None

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        source = cls._work_source(work)
        if not source or cls._provider != source.provider:
            return False
        return cls._transport is None or cls._transport == source.transport

    def map(self, entry):
        """把一个原始条目映射成归一化数据。

        :param entry: 传输产出的原始条目
        :return: dict，键为 ``infohub.item`` 的字段名，外加介质需要的额外键
            （由介质的 ``payload_vals`` 消费）。至少应含 ``title``；
            ``external_id`` 用于同源去重。
        """
        raise NotImplementedError


class ClassifierBase(AbstractComponent):
    """学科归类。用 ``many_components`` 取，允许多个模块各挂一个。

    ``_provider`` / ``_medium`` 为 None 表示不限该维度。
    """

    _name = "infohub.classifier.base"
    _inherit = "infohub.base"
    _usage = "classifier"
    _provider = None
    _medium = None

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        source = cls._work_source(work)
        if not source:
            return False
        if cls._provider is not None and cls._provider != source.provider:
            return False
        if cls._medium is not None and cls._medium != source.medium:
            return False
        return True

    def classify(self, item, entry):
        """为条目指派学科。实现应当就地写 ``item.topic_ids``。"""
        raise NotImplementedError


class EnricherBase(AbstractComponent):
    """条目增强（正文提取、LLM 摘要等）。用 ``many_components`` 取。

    增强通常较慢，应各自派独立 job，不要在采集流水线里同步执行。
    """

    _name = "infohub.enricher.base"
    _inherit = "infohub.base"
    _usage = "enricher"
    _provider = None
    _medium = None

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        source = cls._work_source(work)
        if not source:
            return False
        if cls._provider is not None and cls._provider != source.provider:
            return False
        if cls._medium is not None and cls._medium != source.medium:
            return False
        return True

    def enrich(self, items):
        """增强一批条目。"""
        raise NotImplementedError
