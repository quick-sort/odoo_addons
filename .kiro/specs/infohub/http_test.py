"""InfoHub 前端 HTTP 冒烟测试。

前提：容器里另起一个只服务 test_infohub 的临时 HTTP 服务（见下），因为
``odoo shell`` 自身不启 HTTP 服务，而常驻容器服务的是 odoo 库::

    docker exec -d odoo sh -c "odoo -c /etc/odoo/odoo.conf -d test_infohub \
        --http-port=8099 --gevent-port=8098 --db-filter='^test_infohub$' \
        --workers=0 --max-cron-threads=0 --log-level=error \
        > /tmp/odoo_test_server.log 2>&1"

然后运行本脚本::

    docker exec -i odoo odoo shell -c /etc/odoo/odoo.conf -d test_infohub \
        --no-http --workers=0 < .kiro/specs/infohub/http_test.py

用完停掉临时服务::

    docker exec odoo pkill -f "http-port=8099"

本脚本在 shell 进程里用 requests 打那个服务：两个进程共用同一个库，所以数据
准备完必须 commit 才对服务可见。覆盖：路由可达性、匿名重定向、个性化过滤、
条目详情与"打开即已读"、筛选分页、jsonrpc 端点、CSRF、越权隔离、公开页可见性、
注册限流、注册后读者初始化。
"""

import json
import logging
import re

import requests

logging.disable(logging.WARNING)

BASE = "http://127.0.0.1:8099"
DB = env.cr.dbname
LOGINS = ["web_reader_a", "web_reader_b"]

FAILED = []
PASSED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  ✓ {name}")
    else:
        FAILED.append(f"{name} {detail}".strip())
        print(f"  ✗ {name} {detail}")


print("=" * 70)
print("InfoHub 前端 HTTP 测试")
print("=" * 70)


def cleanup():
    sources = env["infohub.source"].with_context(active_test=False).search(
        [("name", "ilike", "网页测试")]
    )
    items = env["infohub.item"].search([("source_id", "in", sources.ids)])
    env["infohub.blocklist"].with_context(active_test=False).search(
        [("item_id", "in", items.ids)]
    ).unlink()
    env["infohub.source.run"].search([("source_id", "in", sources.ids)]).unlink()
    sources.unlink()
    users = env["res.users"].with_context(active_test=False).search(
        [("login", "in", LOGINS + ["web_signup_sim"])]
    )
    env["infohub.subscription"].search([("user_id", "in", users.ids)]).unlink()
    users.unlink()
    env["infohub.signup.attempt"].sudo().search(
        [("ip", "=like", "203.0.113.%")]
    ).unlink()
    env.cr.commit()


cleanup()

# ======================================================================
# 数据准备（必须 commit：HTTP 服务是另一个进程）
# ======================================================================
Source = env["infohub.source"]
source_a = Source.create({
    "name": "网页测试源 A", "medium": "article", "transport": "rss",
    "provider": "generic", "endpoint": "https://example.com/a.xml",
})
source_b = Source.create({
    "name": "网页测试源 B", "medium": "article", "transport": "rss",
    "provider": "generic", "endpoint": "https://example.com/b.xml",
})

Item = env["infohub.item"]
item_a = Item.create({
    "source_id": source_a.id, "title": "条目甲仅A可见",
    "external_id": "web-a-1", "identity_key": "web-a-1",
    "url": "https://example.com/a/1", "summary": "<p>摘要甲</p>",
    "state": "published", "published_at": "2026-08-20 10:00:00",
})
item_b = Item.create({
    "source_id": source_b.id, "title": "条目乙仅B可见",
    "external_id": "web-b-1", "identity_key": "web-b-1",
    "url": "https://example.com/b/1", "summary": "<p>摘要乙</p>",
    "state": "published", "published_at": "2026-08-21 10:00:00",
})
item_draft = Item.create({
    "source_id": source_a.id, "title": "条目丙未发布",
    "external_id": "web-a-2", "identity_key": "web-a-2", "state": "fetched",
})

portal_group = env.ref("base.group_portal")
reader_group = env.ref("infohub.group_reader")
topic = env.ref("infohub.topic_technology")

users = {}
for login, source in (("web_reader_a", source_a), ("web_reader_b", source_b)):
    user = env["res.users"].create({
        "name": login, "login": login, "password": login,
        "group_ids": [(6, 0, [portal_group.id, reader_group.id])],
    })
    env["infohub.subscription"].create({
        "user_id": user.id, "target_type": "source", "source_id": source.id,
    })
    users[login] = user

env.cr.commit()

# ======================================================================
# HTTP 客户端
# ======================================================================
session = requests.Session()


def get(path, **kw):
    kw.setdefault("timeout", 30)
    return session.get(BASE + path, **kw)


def post(path, data, **kw):
    kw.setdefault("timeout", 30)
    return session.post(BASE + path, data=data, **kw)


def login_as(user_login):
    """用 /web/session/authenticate 登录，拿到 session cookie。"""
    global session
    session = requests.Session()
    resp = session.post(
        BASE + "/web/session/authenticate",
        json={"jsonrpc": "2.0", "method": "call", "params": {
            "db": DB, "login": user_login, "password": user_login}},
        timeout=30,
    )
    return resp.json().get("result", {}).get("uid")


def logout():
    global session
    session = requests.Session()


def jsonrpc(path, params):
    resp = session.post(
        BASE + path,
        json={"jsonrpc": "2.0", "method": "call", "params": params},
        timeout=30,
    )
    return resp.json()


def csrf_from(path="/infohub/subscriptions"):
    page = get(path).text
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page)
    return match.group(1) if match else None


def refresh():
    """让 shell 事务看到 HTTP 进程刚提交的数据。

    Odoo 用 REPEATABLE READ 隔离级别，一个事务的快照在第一条语句时就固定了，
    之后其他进程的提交对它不可见。``invalidate_all()`` 只清 ORM 缓存、不换快照，
    所以必须先 commit 结束当前事务，下一条语句才会拿到新快照。

    这是跨进程测试特有的坑，产品代码里不需要。
    """
    env.cr.commit()
    env.invalidate_all()


# ======================================================================
print("\n[1] 服务可达与匿名访问")
# ======================================================================
logout()
resp = get("/web/login")
check("临时服务可达", resp.status_code == 200, f"(得到 {resp.status_code})")

resp = get("/infohub", allow_redirects=False)
check("匿名访问 /infohub 被重定向", resp.status_code in (302, 303),
      f"(得到 {resp.status_code})")
check("重定向指向登录页", "/web/login" in (resp.headers.get("Location") or ""),
      f"(Location={resp.headers.get('Location')})")

resp = get("/infohub/subscriptions", allow_redirects=False)
check("匿名访问订阅页被重定向", resp.status_code in (302, 303),
      f"(得到 {resp.status_code})")

# ======================================================================
print("\n[2] 个性化：只看到自己订阅的内容")
# ======================================================================
uid = login_as("web_reader_a")
check("读者 A 登录成功", bool(uid), f"(uid={uid})")

resp = get("/infohub")
check("读者 A 能打开信息流", resp.status_code == 200, f"(得到 {resp.status_code})")
body = resp.text
check("读者 A 看到甲", "条目甲仅A可见" in body)
check("读者 A 看不到乙", "条目乙仅B可见" not in body)
check("未发布的丙不出现", "条目丙未发布" not in body)

login_as("web_reader_b")
body = get("/infohub").text
check("读者 B 看到乙", "条目乙仅B可见" in body)
check("读者 B 看不到甲", "条目甲仅A可见" not in body)

# ======================================================================
print("\n[3] 条目详情与打开即已读")
# ======================================================================
login_as("web_reader_a")
resp = get(f"/infohub/item/{item_a.id}")
check("详情页可打开", resp.status_code == 200, f"(得到 {resp.status_code})")
check("详情页渲染标题", "条目甲仅A可见" in resp.text)
check("详情页有原文链接", "https://example.com/a/1" in resp.text)

refresh()
state = env["infohub.item.read"].search([
    ("user_id", "=", users["web_reader_a"].id), ("item_id", "=", item_a.id)])
check("打开详情后写入已读状态", bool(state) and state.is_read,
      f"(找到 {len(state)} 条)")

resp = get(f"/infohub/item/{item_draft.id}", allow_redirects=False)
check("未发布条目被记录规则挡住并重定向", resp.status_code in (302, 303),
      f"(得到 {resp.status_code})")

# ======================================================================
print("\n[4] 筛选、搜索、分页")
# ======================================================================
body = get("/infohub?filterby=unread").text
check("已读条目从未读筛选中消失", "条目甲仅A可见" not in body)

body = get("/infohub?filterby=all").text
check("全部筛选仍能看到已读条目", "条目甲仅A可见" in body)

body = get("/infohub?search=条目甲&search_in=title").text
check("标题搜索命中", "条目甲仅A可见" in body)

body = get("/infohub?search=不存在的关键词xyz").text
check("搜索无结果时给出提示", "没有内容" in body or "放宽条件" in body)

resp = get("/infohub/page/1")
check("分页路由可达", resp.status_code == 200, f"(得到 {resp.status_code})")

resp = get("/infohub?page=abc")
check("非法 page 参数不报错", resp.status_code == 200, f"(得到 {resp.status_code})")

body = get(f"/infohub?topic_id={topic.id}").text
check("学科钻取参数可用（显示筛选提示）", "正在筛选" in body or "清除筛选" in body)

# ======================================================================
print("\n[5] jsonrpc 端点")
# ======================================================================
result = jsonrpc("/infohub/item/toggle_star", {"item_id": item_a.id})
check("收藏切换返回结果", "result" in result, f"(得到 {str(result)[:150]})")
check("收藏状态置为 True", (result.get("result") or {}).get("is_starred") is True,
      f"(得到 {result.get('result')})")

result = jsonrpc("/infohub/item/toggle_star", {"item_id": item_a.id})
check("再次切换取消收藏", (result.get("result") or {}).get("is_starred") is False,
      f"(得到 {result.get('result')})")

result = jsonrpc("/infohub/item/mark_read", {"item_id": item_a.id, "read": False})
check("标为未读端点可用", "result" in result, f"(得到 {str(result)[:150]})")
refresh()
state = env["infohub.item.read"].search([
    ("user_id", "=", users["web_reader_a"].id), ("item_id", "=", item_a.id)])
check("标为未读已落库", state and not state.is_read,
      f"(is_read={state.is_read if state else None})")

result = jsonrpc("/infohub/item/toggle_star", {"item_id": item_draft.id})
check("对不可见条目的 jsonrpc 调用被拒绝", "error" in result,
      f"(得到 {str(result)[:150]})")

# ======================================================================
print("\n[6] 订阅管理与 CSRF")
# ======================================================================
resp = get("/infohub/subscriptions")
check("订阅页可打开", resp.status_code == 200, f"(得到 {resp.status_code})")
check("订阅页列出当前订阅", "网页测试源 A" in resp.text)
check("订阅页含 CSRF 隐藏域", 'name="csrf_token"' in resp.text)

resp = post("/infohub/subscriptions",
            {"action": "remove", "subscription_id": "1"})
check("缺 CSRF 的 POST 被拒绝（400）", resp.status_code == 400,
      f"(得到 {resp.status_code})")

token = csrf_from()
check("能从页面取到 CSRF token", bool(token))

resp = post("/infohub/subscriptions", {
    "csrf_token": token, "action": "add",
    "target_type": "topic", "topic_id": str(topic.id)})
check("带 CSRF 添加学科订阅成功",
      resp.status_code == 200 and "订阅已添加" in resp.text,
      f"(状态 {resp.status_code})")

refresh()
check("订阅确实落库", bool(env["infohub.subscription"].search([
    ("user_id", "=", users["web_reader_a"].id), ("topic_id", "=", topic.id)])))

resp = post("/infohub/subscriptions", {
    "csrf_token": csrf_from(), "action": "add",
    "target_type": "topic", "topic_id": str(topic.id)})
check("重复订阅被拒绝", "已经订阅过" in resp.text)

# ======================================================================
print("\n[7] 越权隔离")
# ======================================================================
other_sub = env["infohub.subscription"].search([
    ("user_id", "=", users["web_reader_b"].id)], limit=1)
check("读者 B 有订阅可作为攻击目标", bool(other_sub))
other_sub_id = other_sub.id

resp = post("/infohub/subscriptions", {
    "csrf_token": csrf_from(), "action": "remove",
    "subscription_id": str(other_sub_id)})
refresh()
check("读者 A 无法删除读者 B 的订阅",
      bool(env["infohub.subscription"].browse(other_sub_id).exists()),
      "(读者 B 的订阅被删掉了！)")
check("越权尝试给出错误提示", "无权" in resp.text or resp.status_code >= 400,
      f"(状态 {resp.status_code})")

resp = post("/infohub/subscriptions", {
    "csrf_token": csrf_from(), "action": "prefs", "lang_filter": "zh,en"})
refresh()
check("读者能保存自己的语言偏好（SELF_WRITEABLE_FIELDS 生效）",
      users["web_reader_a"].infohub_lang_filter == "zh,en",
      f"(得到 {users['web_reader_a'].infohub_lang_filter!r}, 状态 {resp.status_code})")
check("读者 B 的偏好未被影响",
      not users["web_reader_b"].infohub_lang_filter)

# ======================================================================
print("\n[8] 公开学科页")
# ======================================================================
item_a.topic_ids = [(6, 0, [topic.id])]
env.cr.commit()
logout()

resp = get(f"/infohub/topic/{topic.id}")
check("匿名可访问公开学科页", resp.status_code == 200, f"(得到 {resp.status_code})")
check("公开页显示已发布条目", "条目甲仅A可见" in resp.text)
check("公开页有注册引导", "/web/signup" in resp.text)

source_a.access_level = "internal"
env.cr.commit()
resp = get(f"/infohub/topic/{topic.id}")
check("internal 源的条目不出现在公开页", "条目甲仅A可见" not in resp.text)
source_a.access_level = "public"
env.cr.commit()

# ======================================================================
print("\n[9] 注册限流")
# ======================================================================
Attempt = env["infohub.signup.attempt"].sudo()
env["ir.config_parameter"].sudo().set_param("infohub.signup_max_attempts", "3")
env.cr.commit()

results = [Attempt.check_and_record("203.0.113.7") for _ in range(4)]
check("前 3 次注册尝试放行", results[:3] == [True, True, True], f"(得到 {results})")
check("第 4 次被限流拦截", results[3] is False, f"(得到 {results})")
check("其他 IP 不受影响", Attempt.check_and_record("203.0.113.8") is True)
check("IP 为空时不阻断正常注册", Attempt.check_and_record(None) is True)
env["ir.config_parameter"].sudo().set_param("infohub.signup_max_attempts", "5")

# ======================================================================
print("\n[10] 注册后读者初始化")
# ======================================================================
topic.is_recommended = True
env.cr.commit()

new_user = env["res.users"].create({
    "name": "注册模拟", "login": "web_signup_sim",
    "group_ids": [(6, 0, [portal_group.id])],
})
new_user._infohub_init_reader()
refresh()
check("初始化后加入 group_reader", reader_group in new_user.group_ids,
      f"(得到 {new_user.group_ids.mapped('name')})")
subs = env["infohub.subscription"].search([("user_id", "=", new_user.id)])
check("初始化后获得默认订阅", bool(subs), f"(得到 {len(subs)} 条)")
check("默认订阅指向推荐学科", topic in subs.topic_id,
      f"(得到 {subs.mapped('display_name')})")

new_user._infohub_init_reader()
refresh()
check("重复初始化是幂等的",
      len(env["infohub.subscription"].search([("user_id", "=", new_user.id)])) == len(subs))

topic.is_recommended = False
topic.write({"is_recommended": False})

# ======================================================================
print("\n" + "=" * 70)
print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
if FAILED:
    print("\n失败明细：")
    for entry in FAILED:
        print(f"  ✗ {entry}")
print("=" * 70)

cleanup()
print("（测试数据已清理）")
