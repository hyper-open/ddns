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

一个进程可维护**多条记录**（同一服务商）。用 `[[records]]` 列出每条记录，公共项可在 `[ddns]` 里设置默认值、在记录里覆盖：

```toml
[ddns]
provider = "aliyun"        # tencent | aliyun | cloudflare | huawei
check_interval = 60
log_level = "INFO"
# 公共默认值（可被每条记录覆盖）
domain = "example.com"
record_type = "AAAA"
ttl = 600
# state_file = "ddns_state.json"   # 可选，相对路径相对本文件所在目录

[[records]]
domain = "example.com"
sub_domain = "home"        # 前缀；根域名填 "@" 或留空
record_type = "AAAA"

[[records]]
domain = "example.com"
sub_domain = "www"
record_type = "A"
ttl = 300

# 只保留所选服务商对应的段
[aliyun]
region = "cn-hangzhou"     # 可选，用于推导 endpoint
```

省略 `[[records]]` 时，退化为 `[ddns]` 里的单条 `domain`/`sub_domain`。

每条记录的字段：`domain`(未设则用 `[ddns].domain`)、`sub_domain`、`record_type`(`A`/`AAAA`)、`ttl`。

各服务商可选的 `[<provider>]` 段：

| 段 | 选项 | 说明 |
| --- | --- | --- |
| `[tencent]` | 无 | — |
| `[aliyun]` | `region` | 默认 `cn-hangzhou`，用于推导 endpoint |
| `[cloudflare]` | `zone_id`、`proxied` | `zone_id` 可选（填了跳过 zone 查询）；`proxied` 仅对 A 记录生效 |
| `[huawei]` | `region` | **必填** |

`[ddns]` 通用项：`provider`(必填)、`check_interval`、`log_level`、`state_file`，以及可作为默认值的 `domain`、`sub_domain`、`record_type`、`ttl`。

## 多域名 / 多子域名

在同一份 `ddns.toml` 里加多个 `[[records]]` 即可，一个进程启动时解析各自的记录 ID，
循环中**每种记录类型只探测一次公网 IP**，再扇出更新所有记录：

```toml
[ddns]
provider = "aliyun"

[[records]]
domain = "example.com"
sub_domain = "home"
record_type = "AAAA"

[[records]]
domain = "example.com"
sub_domain = "www"
record_type = "AAAA"     # 与上面同类型，共享同一次探测

[[records]]
domain = "other.com"
sub_domain = "@"         # 根域名
record_type = "A"        # IPv4，单独探测一次
```

> 限制：`[[records]]` 共享同一个服务商与凭据。要跨服务商（如 A 域名在阿里云、B 域名在 Cloudflare），
> 仍用下面的多实例方式。

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

## 多服务商同时更新（多实例）

一个进程只更新一个服务商；要让同一 IP 同时同步到多家，**启动多个实例**即可。
推荐"每实例一个目录"的布局：目录内各放一份 `ddns.toml` 与 `.env`，密钥从
**配置文件同级目录**的 `.env` 读取，状态文件默认也落在该目录，实例之间完全隔离。

```text
ddns-instances/
├── aliyun/
│   ├── ddns.toml          # provider = "aliyun"
│   └── .env               # ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET
├── cloudflare/
│   ├── ddns.toml          # provider = "cloudflare"
│   └── .env               # CLOUDFLARE_API_TOKEN
└── tencent/
    ├── ddns.toml          # provider = "tencent"
    └── .env               # TENCENT_ACCESS_KEY_ID / TENCENT_ACCESS_KEY_SECRET
```

各目录的 `ddns.toml`：

```toml
# aliyun/ddns.toml
[ddns]
provider = "aliyun"
record_type = "AAAA"
domain = "example.com"
sub_domain = "home"

[aliyun]
region = "cn-hangzhou"
```

```toml
# cloudflare/ddns.toml
[ddns]
provider = "cloudflare"
record_type = "AAAA"
domain = "example.com"
sub_domain = "home"

[cloudflare]
proxied = false
```

```toml
# tencent/ddns.toml
[ddns]
provider = "tencent"
record_type = "AAAA"
domain = "example.com"
sub_domain = "home"

[tencent]
```

用 `DDNS_CONFIG` 指定实例，分别启动（每个进程用自己的配置与状态文件）：

```bash
DDNS_CONFIG=./ddns-instances/aliyun/ddns.toml     python -m ddns &
DDNS_CONFIG=./ddns-instances/cloudflare/ddns.toml python -m ddns &
DDNS_CONFIG=./ddns-instances/tencent/ddns.toml    python -m ddns &
```

systemd 单元示例（每实例一个 unit）：

```ini
[Unit]
Description=DDNS (aliyun)
After=network-online.target

[Service]
WorkingDirectory=/opt/ddns-instances/aliyun
Environment=DDNS_CONFIG=/opt/ddns-instances/aliyun/ddns.toml
ExecStart=/usr/bin/python3 -m ddns
Restart=always

[Install]
WantedBy=multi-user.target
```

> 状态文件按 `provider:record_type:fqdn` 分键，即使多个实例共用同一个状态文件也不会互相误判；
> 但为避免并发写竞态，仍建议每实例独立目录。

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

