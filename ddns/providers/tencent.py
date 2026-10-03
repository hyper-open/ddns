"""腾讯云 DNSPod 服务商。"""
from typing import Optional

from ..config import Config
from .base import BaseProvider, Target, require_module


class TencentProvider(BaseProvider):
    name = "tencent"
    required_settings = ("TENCENT_ACCESS_KEY_ID", "TENCENT_ACCESS_KEY_SECRET")

    def __init__(self, target: Target, client, models=None, sdk_error=None):
        super().__init__(target)
        self._client = client
        self._models = models or require_module(
            "tencentcloud.dnspod.v20210323.models", "tencent"
        )
        self._sdk_error = sdk_error or require_module(
            "tencentcloud.common.exception.tencent_cloud_sdk_exception", "tencent"
        ).TencentCloudSDKException

    @classmethod
    def from_config(cls, cfg: Config) -> "TencentProvider":
        credential = require_module("tencentcloud.common.credential", "tencent")
        dnspod_client = require_module(
            "tencentcloud.dnspod.v20210323.dnspod_client", "tencent"
        )
        cred = credential.Credential(
            cfg.credential("TENCENT_ACCESS_KEY_ID"),
            cfg.credential("TENCENT_ACCESS_KEY_SECRET"),
        )
        client = dnspod_client.DnspodClient(cred, "")  # DNSPod 为全局服务，region 传空
        target = Target(cfg.domain, cfg.sub_domain, cfg.record_type, cfg.ttl)
        return cls(target, client)

    def resolve_record_id(self) -> Optional[str]:
        req = self._models.DescribeRecordListRequest()
        req.Domain = self.target.domain
        req.Subdomain = self.target.host
        req.RecordType = self.target.record_type
        try:
            resp = self._client.DescribeRecordList(req)
            if resp.RecordList and len(resp.RecordList) > 0:
                return resp.RecordList[0].RecordId
            self.log.error(
                "未找到 %s 的 %s 记录，请先在控制台手动创建",
                self.target.fqdn, self.target.record_type,
            )
            return None
        except self._sdk_error as e:
            self.log.error("查询记录ID失败: %s", e)
            return None

    def update(self, record_id: str, ip: str) -> bool:
        req = self._models.ModifyRecordRequest()
        req.Domain = self.target.domain
        req.RecordId = record_id
        req.SubDomain = self.target.host
        req.RecordType = self.target.record_type
        req.RecordLine = "默认"
        req.Value = ip
        req.TTL = self.target.ttl
        try:
            resp = self._client.ModifyRecord(req)
            self.log.info(
                "DNS更新成功: %s -> %s (RecordId=%s)",
                self.target.fqdn, ip, resp.RecordId,
            )
            return True
        except self._sdk_error as e:
            self.log.error("DNS更新失败: %s", e)
            return False
