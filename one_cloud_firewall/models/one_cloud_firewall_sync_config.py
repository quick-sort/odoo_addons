# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import ipaddress
import logging
import socket
from urllib.parse import urlsplit, urlunsplit

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_IP_SERVICE_URL = "http://ipaddress.ai/json"


class CloudFirewallSyncConfig(models.Model):
    _name = "one.cloud.firewall.sync.config"
    _description = "防火墙同步配置"
    _rec_name = "ip_service_url"

    ip_service_url = fields.Char(
        required=True,
        string="公网 IP 查询服务",
        default=DEFAULT_IP_SERVICE_URL,
        help="需返回 JSON 格式 {\"ip\": \"x.x.x.x\"}。建议使用 http:// 地址以确保强制走 IPv4",
    )
    current_ip = fields.Char(readonly=True, string="当前公网 IP")
    last_sync = fields.Datetime(readonly=True, string="最近同步时间")

    @api.model
    def _get_singleton(self):
        config = self.search([], limit=1)
        return config or self.create(
            {"ip_service_url": DEFAULT_IP_SERVICE_URL}
        )

    @api.model
    def action_open_config(self):
        config = self._get_singleton()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": config.id,
            "view_mode": "form",
        }

    def action_fetch_current_ip(self):
        self.ensure_one()
        ip = self._fetch_public_ip()
        self.current_ip = ip
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("获取当前 IP"),
                "message": _("当前公网 IP: %s", ip),
                "type": "success",
                # 弹消息后重载当前视图，让表单刷新显示最新 IP
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_run_cron(self):
        """手工触发定时同步（与 ir.cron 同一入口，供测试与立即执行）。"""
        self.ensure_one()
        try:
            self.env["one.cloud.firewall.target"].cron_sync_all()
        except Exception as exc:
            _logger.exception("手工触发防火墙同步失败")
            raise UserError(_("执行定时同步失败: %s", exc)) from exc
        config = self.env["one.cloud.firewall.sync.config"]._get_singleton()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("定时同步"),
                "message": _(
                    "同步完成，当前 IP: %(ip)s，最近同步: %(when)s",
                    ip=config.current_ip or "-",
                    when=config.last_sync or "-",
                ),
                "type": "success",
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def _fetch_public_ip(self):
        self.ensure_one()
        import requests

        url = self.ip_service_url
        parts = urlsplit(url)
        kwargs = {"timeout": 10}
        if parts.scheme == "http" and parts.hostname:
            # 强制 IPv4：仅解析 A 记录，用字面 IP 连接并保留 Host 头
            # （不 monkey-patch urllib3，那在多线程 Odoo 服务器上不安全）
            infos = socket.getaddrinfo(
                parts.hostname, parts.port or 80, socket.AF_INET, socket.SOCK_STREAM
            )
            addr = infos[0][4][0]
            netloc = f"{addr}:{parts.port}" if parts.port else addr
            ip_url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
            resp = requests.get(ip_url, headers={"Host": parts.hostname}, **kwargs)
        else:
            resp = requests.get(url, **kwargs)
        if not resp.ok:
            raise UserError(
                _("IP 查询服务返回 HTTP %s: %s", resp.status_code, resp.text[:500])
            )
        ip = (resp.json() or {}).get("ip", "")
        try:
            version = ipaddress.ip_address(ip).version
        except ValueError:
            version = None
        if version != 4:
            raise UserError(_("获取到的不是 IPv4 地址: %s", ip))
        return ip
