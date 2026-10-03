# tencent-ddns

腾讯云 DNSPod IPv6 动态域名解析（DDNS）脚本。周期性探测本机公网 IPv6，发生变化时自动更新 DNSPod 上的 AAAA 记录，适合家宽 IPv6 前缀不固定、又需要稳定域名访问的场景。

## 特性

- **混合探测**：优先本地 socket 探测（快、无外部依赖），再用外部 API 回看校验；本地拿不到时自动回退外部 API，尽可能拿到真实可路由的 IPv6。
- **多 API 容灾**：内置多个 IPv6 查询接口，逐个尝试，任一可用即可。
- **地址校验**：过滤回环、链路本地、ULA 内网等非法地址，避免把内网地址写进 DNS。
- **状态持久化**：记录上次同步的地址（`last_ipv6.txt`），地址未变化时不重复调用 API。
- **忽略系统代理**：避免本机 HTTP 代理不支持 IPv6 导致 TLS 中断。

## 环境要求

- Python 3.8+
- 一台具备可用公网 IPv6 的机器
- 腾讯云账号，已开通 DNSPod，并在控制台为目标子域名**手动创建一条 AAAA 记录**（脚本只更新、不负责首次创建）

## 安装

```bash
pip install -r requirements.txt
```

## 配置

```bash
cp .env.example .env
```

编辑 `.env`：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `TENCENT_SECRET_ID` | 腾讯云 API 密钥 SecretId | 必填 |
| `TENCENT_SECRET_KEY` | 腾讯云 API 密钥 SecretKey | 必填 |
| `DDNS_DOMAIN` | 主域名，如 `example.com` | `example.com` |
| `DDNS_SUB_DOMAIN` | 子域名前缀，如 `home.example.com` 就填 `home` | `home` |
| `DDNS_CHECK_INTERVAL` | 检测间隔（秒） | `60` |

建议使用仅授权 DNSPod 权限的最小权限子账号密钥。

## 运行

```bash
python ddns_tencent.py
```

输出示例：

```
启动 DDNS 监控 | 域名: home.example.com | RecordId: 123456789
🔄 IPv6变化: None -> 2409:8a1e:xxxx::1
✅ DNS更新成功: home.example.com -> 2409:8a1e:xxxx::1  (RecordId=123456789)
⏸️ IPv6未变化: 2409:8a1e:xxxx::1
```

## 测试

```bash
python -m unittest -v test_ddns_tencent
```

测试通过 mock 覆盖地址校验、多 API 回退、探测降级、状态文件读写与 DNS 记录操作等边界情况，**不需要真实密钥，也不会发起真实请求**。

## 安全提示

- `.env` 含真实密钥，已在 `.gitignore` 中忽略，**切勿提交**。
- 状态文件 `last_ipv6.txt` 同样不入库。

## 许可证

[MIT](LICENSE)
