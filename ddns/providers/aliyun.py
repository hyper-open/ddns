"""阿里云云解析 DNS 服务商。"""
from typing import Optional

from ..config import Config
from .base import BaseProvider, Target, require_module


class AliyunProvider(BaseProvider):
    name = "aliyun"
    required_settings = ("ALIYUN_ACCESS_KEY_ID", "ALIYUN_ACCESS_KEY_SECRET")

    def __init__(self, target: Target, client, models):
        super().__init__(target)
        self._client = client
        self._models = models

    @classmethod
    def from_config(cls, cfg: Config) -> "AliyunProvider":
        client_mod = require_module("alibabacloud_alidns20150109.client", "aliyun")
        models = require_module("alibabacloud_alidns20150109.models", "aliyun")
        open_api_models = require_module("alibabacloud_tea_openapi.models", "aliyun")
        region = cfg.option("region", "cn-hangzhou")
        config = open_api_models.Config(
            access_key_id=cfg.credential("ALIYUN_ACCESS_KEY_ID"),
            access_key_secret=cfg.credential("ALIYUN_ACCESS_KEY_SECRET"),
            endpoint=f"alidns.{region}.aliyuncs.com",
        )
        client = client_mod.Client(config)
        target = Target(cfg.domain, cfg.sub_domain, cfg.record_type, cfg.ttl)
        return cls(target, client, models)

    def resolve_record_id(self) -> Optional[str]:
        req = self._models.DescribeDomainRecordsRequest(
            domain_name=self.target.domain,
            rr=self.target.host,
            type=self.target.record_type,
        )
        try:
            resp = self._client.describe_domain_records(req)
            records = resp.body.domain_records.record or []
            if records:
                return records[0].record_id
            self.log.error(
                "未找到 %s 的 %s 记录，请先在控制台手动创建",
                self.target.fqdn, self.target.record_type,
            )
            return None
        except Exception as e:  # noqa: BLE001
            self.log.error("查询记录ID失败: %s", e)
            return None

    def update(self, record_id: str, ip: str) -> bool:
        req = self._models.UpdateDomainRecordRequest(
            record_id=record_id,
            rr=self.target.host,
            type=self.target.record_type,
            value=ip,
            ttl=self.target.ttl,
        )
        try:
            self._client.update_domain_record(req)
            self.log.info("DNS更新成功: %s -> %s", self.target.fqdn, ip)
            return True
        except Exception as e:  # noqa: BLE001
            self.log.error("DNS更新失败: %s", e)
            return False
