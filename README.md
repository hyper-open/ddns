# ddns

通用动态域名解析（DDNS）工具：周期探测本机公网 IP，发生变化时自动更新多家 DNS 服务商的记录。适合家宽 IPv4/IPv6 地址不固定、又需要稳定域名访问的场景。

支持的服务商：

| `DDNS_PROVIDER` | 服务商 | 依赖 |
| --- | --- | --- |
| `dnspod` | 腾讯云 DNSPod | `tencentcloud-sdk-python` |
| `aliyun` | 阿里云云解析 DNS | `alibabacloud_alidns20150109` |
| `cloudflare` | Cloudflare | 无（纯 REST） |
| `huawei` | 华为云 DNS | `huaweicloudsdkdns` |

每次进程只更新一个服务商，由 `DDNS_PROVIDER` 指定；支持 `A`（IPv4）与 `AAAA`（IPv6）记录。

## 特性

- **多服务商**：一套配置切换腾讯云/阿里云/Cloudflare/华为云。
- **混合探测**：优先本地 socket 探测（快、无外部依赖），再用外部 API 回看校验；本地拿不到时回退外部 API，尽可能拿到真实可路由的地址。
- **多 API 容灾**：内置多个公网 IP 查询接口，逐个尝试，任一可用即可。
- **地址校验**：过滤私有、回环、链路本地、ULA、CGNAT、文档保留段等非法地址，避免把不可路由的地址写进 DNS。
- **状态持久化**：记录上次同步的地址，地址未变化时不重复调用 API。
- **忽略系统代理**：避免本机 HTTP 代理不支持 IPv6 导致 TLS 中断。
- **可选依赖**：只为所选服务商安装对应 SDK。

## 环境要求

- Python 3.8+
- 一台具备可用公网 IP 的机器
- 对应 DNS 服务商账号，并已在控制台为目标记录**手动创建一条 A/AAAA 记录**（本工具只更新、不负责首次创建）

## 安装

```bash
pip install -r requirements.txt

# 再按服务商安装对应 SDK（四选一）：
pip install "ddns[dnspod]"       # 腾讯云
pip install "ddns[aliyun]"       # 阿里云
pip install "ddns[cloudflare]"   # Cloudflare（无额外依赖）
pip install "ddns[huawei]"       # 华为云
```

未以可安装方式引入时，也可直接 `pip install tencentcloud-sdk-python`（或对应 SDK）后运行。

## 配置

```bash
cp .env.example .env
```

编辑 `.env`。**只会校验所选服务商对应的凭据**，其他留空即可。

### 通用

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `DDNS_PROVIDER` | `dnspod` / `aliyun` / `cloudflare` / `huawei` | 必填 |
| `DDNS_RECORD_TYPE` | `AAAA`(IPv6) 或 `A`(IPv4) | `AAAA` |
| `DDNS_DOMAIN` | 主域名，如 `example.com` | `example.com` |
| `DDNS_SUB_DOMAIN` | 主机记录前缀，如 `home.example.com` 填 `home`；根域名填 `@` 或留空 | 空 |
| `DDNS_TTL` | 记录 TTL（秒） | `600` |
| `DDNS_CHECK_INTERVAL` | 检测间隔（秒） | `60` |
| `DDNS_STATE_FILE` | 可选，状态文件路径 | `ddns_state.json` |
| `DDNS_LOG_LEVEL` | `DEBUG`/`INFO`/`WARNING`/`ERROR` | `INFO` |

### 各服务商凭据

| 服务商 | 变量 |
| --- | --- |
| 腾讯云 | `TENCENT_SECRET_ID`、`TENCENT_SECRET_KEY` |
| 阿里云 | `ALIYUN_ACCESS_KEY_ID`、`ALIYUN_ACCESS_KEY_SECRET`、`ALIYUN_REGION`(默认 `cn-hangzhou`) |
| Cloudflare | `CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ZONE_ID`(可选)、`CLOUDFLARE_PROXIED`(默认 `false`) |
| 华为云 | `HUAWEI_ACCESS_KEY_ID`、`HUAWEI_SECRET_ACCESS_KEY`、`HUAWEI_REGION` |

建议使用仅授权 DNS 权限的最小权限密钥。

## 运行

```bash
python -m ddns
# 或安装后
ddns
```

输出示例：

```
2026-10-03 09:40:00 INFO 启动 DDNS 监控 | 服务商: aliyun | 记录: home.example.com (AAAA) | RecordId: 99****
2026-10-03 09:40:01 INFO AAAA 变化: None -> 2409:8a1e:xxxx::1
2026-10-03 09:40:01 INFO DNS更新成功: home.example.com -> 2409:8a1e:xxxx::1
2026-10-03 09:41:01 INFO AAAA 未变化: 2409:8a1e:xxxx::1
```

## 测试

```bash
python -m unittest discover -s tests -t .
# 或
pip install "ddns[dev]" && pytest
```

测试通过 mock 覆盖地址校验、多 API 回退、探测降级、状态读写与各服务商的记录解析/更新（含主机记录归一化）等边界情况，**不需要真实密钥，也不会发起真实请求**。未安装任何厂商 SDK 时核心测试仍可全绿。

## 安全提示

- `.env` 含真实密钥，已在 `.gitignore` 中忽略，**切勿提交**。
- 状态文件 `ddns_state.json` 同样不入库。

## 许可证

[MIT](LICENSE)
