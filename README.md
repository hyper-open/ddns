# ddns

通用动态域名解析（DDNS）工具：周期探测本机公网 IP，发生变化时自动更新多家 DNS 服务商的记录。适合家宽 IPv4/IPv6 地址不固定、又需要稳定域名访问的场景。

支持的服务商：

| `provider` | 服务商 | 依赖 |
| --- | --- | --- |
| `tencent` | 腾讯云 DNSPod | `tencentcloud-sdk-python` |
| `aliyun` | 阿里云云解析 DNS | `alibabacloud_alidns20150109` |
| `cloudflare` | Cloudflare | 无（纯 REST） |
| `huawei` | 华为云 DNS | `huaweicloudsdkdns` |

每次进程只更新一个服务商，由 `ddns.toml` 中的 `provider` 指定；支持 `A`（IPv4）与 `AAAA`（IPv6）记录。

## 特性

- **多服务商**：一套配置切换腾讯云/阿里云/Cloudflare/华为云。
- **配置与密钥分离**：非敏感配置放 `ddns.toml`（含 `[<provider>]` 分段），密钥放 `.env`，互不混杂。
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
pip install "ddns[tencent]"      # 腾讯云
pip install "ddns[aliyun]"       # 阿里云
pip install "ddns[cloudflare]"   # Cloudflare（无额外依赖）
pip install "ddns[huawei]"       # 华为云
```

未以可安装方式引入时，也可直接 `pip install tencentcloud-sdk-python`（或对应 SDK）后运行。

## 配置

配置拆成两份：**非敏感项在 `ddns.toml`，密钥在 `.env`**。

```bash
cp ddns.toml.example ddns.toml
cp .env.example .env
```

### `ddns.toml`

```toml
[ddns]
provider = "aliyun"        # tencent | aliyun | cloudflare | huawei
record_type = "AAAA"       # AAAA(IPv6) | A(IPv4)
domain = "example.com"
sub_domain = "home"        # 前缀；根域名填 "@" 或留空
ttl = 600
check_interval = 60
log_level = "INFO"
# state_file = "ddns_state.json"   # 可选

# 只保留所选服务商对应的段
[aliyun]
region = "cn-hangzhou"     # 可选，用于推导 endpoint
```

各服务商可选的 `[<provider>]` 段：

| 段 | 选项 | 说明 |
| --- | --- | --- |
| `[tencent]` | 无 | — |
| `[aliyun]` | `region` | 默认 `cn-hangzhou`，用于推导 endpoint |
| `[cloudflare]` | `zone_id`、`proxied` | `zone_id` 可选（填了跳过 zone 查询）；`proxied` 仅对 A 记录生效 |
| `[huawei]` | `region` | **必填** |

`[ddns]` 通用项：`provider`(必填)、`record_type`、`domain`、`sub_domain`、`ttl`、`check_interval`、`log_level`、`state_file`。

### `.env`（密钥）

变量按服务商统一命名，只需填你所用 provider 对应的：

| 服务商 | 变量 |
| --- | --- |
| 腾讯云 | `TENCENT_ACCESS_KEY_ID`、`TENCENT_ACCESS_KEY_SECRET` |
| 阿里云 | `ALIYUN_ACCESS_KEY_ID`、`ALIYUN_ACCESS_KEY_SECRET` |
| Cloudflare | `CLOUDFLARE_API_TOKEN` |
| 华为云 | `HUAWEI_ACCESS_KEY_ID`、`HUAWEI_ACCESS_KEY_SECRET` |

只会校验所选服务商的凭据。建议使用仅授权 DNS 权限的最小权限密钥。

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

测试通过 mock 覆盖配置加载、地址校验、多 API 回退、探测降级、状态读写与各服务商的记录解析/更新（含主机记录归一化）等边界情况，**不需要真实密钥，也不会发起真实请求**。未安装任何厂商 SDK 时核心测试仍可全绿。

## 安全提示

- `.env` 含真实密钥，已在 `.gitignore` 中忽略，**切勿提交**。
- `ddns.toml` 也可能含 zone id 等隐私信息，同样已忽略；仅 `*.example` 模板入库。
- 状态文件 `ddns_state.json` 同样不入库。

## 许可证

[MIT](LICENSE)

