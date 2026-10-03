"""Cloudflare 服务商（纯 REST，无需厂商 SDK）。"""
from typing import Optional

import requests

from ..config import Config
from .base import BaseProvider, Target

API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareProvider(BaseProvider):
    name = "cloudflare"
    required_settings = ("CLOUDFLARE_API_TOKEN",)

    def __init__(self, target: Target, token: str, zone_id: Optional[str],
                 proxied: bool = False, session=None):
        super().__init__(target)
        self._token = token
        self._zone_id = zone_id
        self._proxied = proxied
        self._session = session or requests.Session()
        self._session.trust_env = False

    @staticmethod
    def build_client(cfg: Config):
        session = requests.Session()
        session.trust_env = False  # 忽略系统代理，避免 IPv6 走代理中断
        return session

    @classmethod
    def from_config(cls, cfg: Config, target=None, client=None) -> "CloudflareProvider":
        target = target or Target(cfg.records[0].domain, cfg.records[0].sub_domain,
                                  cfg.records[0].record_type, cfg.records[0].ttl)
        return cls(
            target,
            cfg.credential("CLOUDFLARE_API_TOKEN"),
            cfg.option("zone_id"),
            bool(cfg.option("proxied", False)),
            session=client or cls.build_client(cfg),
        )

    def _headers(self):
        return {"Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json"}

    def _request(self, method, path, **kwargs):
        url = f"{API_BASE}{path}"
        resp = self._session.request(method, url, headers=self._headers(),
                                     timeout=10, **kwargs)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"Cloudflare API 错误: {data.get('errors')}")
        return data

    def _get_zone_id(self) -> Optional[str]:
        if self._zone_id:
            return self._zone_id
        try:
            data = self._request("GET", "/zones", params={"name": self.target.domain})
            results = data.get("result") or []
            if not results:
                self.log.error("未找到域名 %s 对应的 zone", self.target.domain)
                return None
            return results[0]["id"]
        except Exception as e:  # noqa: BLE001
            self.log.error("查询 zone 失败: %s", e)
            return None

    def resolve_record_id(self) -> Optional[str]:
        zone_id = self._get_zone_id()
        if not zone_id:
            return None
        try:
            data = self._request(
                "GET", f"/zones/{zone_id}/dns_records",
                params={"type": self.target.record_type, "name": self.target.fqdn},
            )
            results = data.get("result") or []
            if not results:
                self.log.error(
                    "未找到 %s 的 %s 记录，请先在控制台手动创建",
                    self.target.fqdn, self.target.record_type,
                )
                return None
            return results[0]["id"]
        except Exception as e:  # noqa: BLE001
            self.log.error("查询记录ID失败: %s", e)
            return None

    def update(self, record_id: str, ip: str) -> bool:
        zone_id = self._get_zone_id()
        if not zone_id:
            return False
        body = {"content": ip}
        if self.target.record_type == "A":
            body["proxied"] = self._proxied
        try:
            self._request("PATCH", f"/zones/{zone_id}/dns_records/{record_id}",
                          json=body)
            self.log.info("DNS更新成功: %s -> %s", self.target.fqdn, ip)
            return True
        except Exception as e:  # noqa: BLE001
            self.log.error("DNS更新失败: %s", e)
            return False
