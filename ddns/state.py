"""IP 状态持久化，避免地址未变化时重复调用服务商 API。"""
import json
import logging
from pathlib import Path

log = logging.getLogger("ddns.state")


class StateStore:
    """以 JSON 字典保存多组 key -> ip 映射。

    key 形如 ``provider:record_type:fqdn``，切换服务商或记录类型时不会
    误判为"未变化"。
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError) as e:
            log.warning("读取状态文件失败，按空状态处理: %s", e)
            return {}

    def get(self, key: str):
        return self._data.get(key)

    def set(self, key: str, ip: str) -> None:
        self._data[key] = ip
        self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError as e:
            log.warning("写入状态文件失败: %s", e)
