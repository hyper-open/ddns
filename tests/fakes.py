"""测试共享的假对象。"""


class FakeResp:
    def __init__(self, text="", payload=None, status=200):
        self.text = text
        self._payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self._payload


class FakeSession:
    """按 url 返回预设响应；值可为异常实例以示连接失败。

    get/request 均可路由；mapping 的 key 用 url 前缀匹配（含 query 时以 url 为准）。
    """

    def __init__(self, mapping=None, responder=None):
        self.mapping = mapping or {}
        self.responder = responder
        self.calls = []
        self.requests = []

    trust_env = True

    def get(self, url, timeout=None, **kwargs):
        self.calls.append(url)
        if self.responder is not None:
            return self.responder("GET", url, None)
        val = self.mapping.get(url, RuntimeError("no route"))
        if isinstance(val, Exception):
            raise val
        return val

    def request(self, method, url, headers=None, timeout=None, **kwargs):
        self.requests.append((method, url, kwargs))
        if self.responder is not None:
            return self.responder(method, url, kwargs)
        val = self.mapping.get(url, RuntimeError("no route"))
        if isinstance(val, Exception):
            raise val
        return val
