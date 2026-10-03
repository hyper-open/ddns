"""华为云 DNS 服务商。"""
from typing import Optional

from ..config import Config
from .base import BaseProvider, Target, require_module


class HuaweiProvider(BaseProvider):
    name = "huawei"
    required_settings = (
        "HUAWEI_ACCESS_KEY_ID",
        "HUAWEI_ACCESS_KEY_SECRET",
        "region",
    )

    def __init__(self, target: Target, client, models):
        super().__init__(target)
        self._client = client
        self._models = models

    @classmethod
    def from_config(cls, cfg: Config) -> "HuaweiProvider":
        credentials = require_module(
            "huaweicloudsdkcore.auth.credentials", "huawei"
        )
        dns_client = require_module("huaweicloudsdkdns.v2", "huawei")
        region = require_module("huaweicloudsdkdns.v2.region.dns_region", "huawei")
        client = (
            dns_client.DnsClient.new_builder()
            .with_credentials(
                credentials.BasicCredentials(
                    cfg.credential("HUAWEI_ACCESS_KEY_ID"),
                    cfg.credential("HUAWEI_ACCESS_KEY_SECRET"),
                )
            )
            .with_region(region.DnsRegion.value_of(cfg.option("region")))
            .build()
        )
        target = Target(cfg.domain, cfg.sub_domain, cfg.record_type, cfg.ttl)
        return cls(target, client, dns_client)

    def _zone_id(self) -> Optional[str]:
        req = self._models.ListPublicZonesRequest(name=self.target.domain)
        try:
            resp = self._client.list_public_zones(req)
            zones = resp.zones or []
            if not zones:
                self.log.error("未找到域名 %s 对应的公网 zone", self.target.domain)
                return None
            return zones[0].id
        except Exception as e:  # noqa: BLE001
            self.log.error("查询 zone 失败: %s", e)
            return None

    def resolve_record_id(self) -> Optional[str]:
        zone_id = self._zone_id()
        if not zone_id:
            return None
        req = self._models.ListRecordSetsByZoneRequest(
            zone_id=zone_id,
            type=self.target.record_type,
            name=self.target.fqdn,
        )
        try:
            resp = self._client.list_record_sets_by_zone(req)
            recordsets = resp.recordsets or []
            if recordsets:
                return recordsets[0].id
            self.log.error(
                "未找到 %s 的 %s 记录，请先在控制台手动创建",
                self.target.fqdn, self.target.record_type,
            )
            return None
        except Exception as e:  # noqa: BLE001
            self.log.error("查询记录ID失败: %s", e)
            return None

    def update(self, record_id: str, ip: str) -> bool:
        zone_id = self._zone_id()
        if not zone_id:
            return False
        req = self._models.UpdateRecordSetRequest(
            zone_id=zone_id,
            recordset_id=record_id,
            records=[ip],
        )
        try:
            self._client.update_record_set(req)
            self.log.info("DNS更新成功: %s -> %s", self.target.fqdn, ip)
            return True
        except Exception as e:  # noqa: BLE001
            self.log.error("DNS更新失败: %s", e)
            return False
