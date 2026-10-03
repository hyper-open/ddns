# ddns

跨服务商的动态域名解析（DDNS）工具。周期探测本机公网 IP，发生变化时自动更新 DNS 记录。

适合家宽 / 拨号线路 IPv4、IPv6 地址不固定，又需要稳定域名访问的场景（远程回家、自建服务、NAS、软路由等）。

支持的 DNS 服务商：

| `provider` | 服务商 | 依赖 |
| --- | --- | --- |
| `tencent` | 腾讯云 DNSPod | `tencentcloud-sdk-python` |
| `aliyun` | 阿里云云解析 DNS | `alibabacloud_alidns20150109` |
| `cloudflare` | Cloudflare | 无（纯 REST） |
| `huawei` | 华为云 DNS | `huaweicloudsdkdns` |

## 特性

- **多服务商**：一份配置切换腾讯云 / 阿里云 / Cloudflare / 华为云，切换只改一行。
- **IPv4 + IPv6**：同时支持 `A` 与 `AAAA` 记录，按记录类型独立探测。
- **单进程多记录**：一份配置维护多个域名 / 子域名；每种记录类型每轮只探测一次 IP，再扇出更新。
- **配置与密钥分离**：非敏感项放 `ddns.toml`（含 `[<provider>]` 分段），密钥放 `.env`。
- **混合探测**：优先本地 socket 探测出口地址（快、无外部依赖），再用外部 API 从公网侧回看校验；两者不一致以公网为准，公网不可用时降级本地。
- **多 API 容灾**：内置多个公网 IP 查询接口，逐个尝试，任一可用即可。
- **严格地址校验**：过滤私有、回环、链路本地、ULA、CGNAT、文档保留段等，避免把不可路由地址写进 DNS。
- **状态持久化**：记录上次同步地址，未变化不调 API；状态文件按 `provider:record_type:fqdn` 分键。
- **忽略系统代理**：避免本机 HTTP 代理不支持 IPv6 导致 TLS 中断。
- **可选依赖**：只为实际使用的服务商安装 SDK。
- **零厂商 SDK 也能测**：全部测试基于 mock，不联网、不需要密钥。

## 环境要求

- Python 3.8+
- 一台具可用公网 IP 的机器（探测端）
- 对应 DNS 服务商账号，且已在控制台**手动创建**目标 A/AAAA 记录（本工具只更新，不负责首次创建）

## 安装

```bash
git clone git@github.com:hyper-open/ddns.git
cd ddns

# 按服务商安装（以阿里云为例），会把核心依赖一并装上：
pip install -e ".[aliyun]"
```

> 尚未发布到 PyPI。`-e`（可编辑安装）便于后续 `git pull` 直接生效；
> 不想安装也可只装依赖后直接 `python -m ddns` 运行。

各服务商对应的 extra：

```bash
pip install -e ".[tencent]"     # 腾讯云
pip install -e ".[aliyun]"      # 阿里云
pip install -e ".[cloudflare]"  # Cloudflare（无额外依赖）
pip install -e ".[huawei]"      # 华为云
pip install -e ".[all]"         # 全装（调试用）
```

## 快速开始

```bash
# 1. 复制配置模板
cp ddns.toml.example ddns.toml
cp .env.example .env

# 2. 编辑 ddns.toml（选服务商、填域名），编辑 .env（填密钥）
# 3. 运行
python -m ddns
```

## 配置

配置分两份：**非敏感项在 `ddns.toml`，密钥在 `.env`**（两者同名 `.env` 会被自动加载，无需额外设置）。

### `ddns.toml`

```toml
[ddns]
provider = "aliyun"        # tencent | aliyun | cloudflare | huawei
check_interval = 60        # 检测间隔（秒）
log_level = "INFO"         # DEBUG | INFO | WARNING | ERROR
# state_file = "ddns_state.json"   # 可选；相对路径相对本文件所在目录

# 公共默认值，可被每条记录覆盖
domain = "example.com"
record_type = "AAAA"
ttl = 600

[[records]]
sub_domain = "home"

[[records]]
sub_domain = "www"
record_type = "A"
ttl = 300

# 只保留所选服务商对应的段
[aliyun]
region = "cn-hangzhou"
```

**字段说明**

`[ddns]` 通用项：

| 键 | 必填 | 说明 | 默认 |
| --- | --- | --- | --- |
| `provider` | ✅ | `tencent` / `aliyun` / `cloudflare` / `huawei` | — |
| `check_interval` | | 检测间隔（秒） | `60` |
| `log_level` | | 日志级别 | `INFO` |
| `state_file` | | 状态文件路径 | 本文件同目录 `ddns_state.json` |
| `domain` | | 默认主域名 | `example.com` |
| `sub_domain` | | 默认主机前缀；根域名用 `@` 或留空 | 空 |
| `record_type` | | 默认记录类型 `A` / `AAAA` | `AAAA` |
| `ttl` | | 默认 TTL（秒） | `600` |

`[[records]]` 每条记录可写：`domain`、`sub_domain`、`record_type`、`ttl`，未写的从 `[ddns]` 继承。

> 省略 `[[records]]` 时，退化为 `[ddns]` 里的单条记录（向后兼容）。

**各服务商段 `[<provider>]`**

| 段 | 选项 | 必填 | 说明 |
| --- | --- | --- | --- |
| `[tencent]` | — | | 无额外选项 |
| `[aliyun]` | `region` | | 默认 `cn-hangzhou`，用于推导 endpoint |
| `[cloudflare]` | `zone_id` | | 可选；填了跳过 zone 查询 |
| | `proxied` | | 仅对 A 记录生效，默认 `false` |
| `[huawei]` | `region` | ✅ | 如 `cn-north-4` |

### `.env`（密钥）

只校验所选服务商对应的变量，其他留空即可：

| 服务商 | 变量 |
| --- | --- |
| 腾讯云 | `TENCENT_ACCESS_KEY_ID`、`TENCENT_ACCESS_KEY_SECRET` |
| 阿里云 | `ALIYUN_ACCESS_KEY_ID`、`ALIYUN_ACCESS_KEY_SECRET` |
| Cloudflare | `CLOUDFLARE_API_TOKEN` |
| 华为云 | `HUAWEI_ACCESS_KEY_ID`、`HUAWEI_ACCESS_KEY_SECRET` |

建议使用**仅授权 DNS 权限的最小权限密钥**（子账号 / RAM / API Token）。

## 样例

`examples/` 下每个文件都是一份完整 `ddns.toml`，复制即用（记得同步填 `.env`）：

| 文件 | 场景 |
| --- | --- |
| [`examples/tencent-ipv6.toml`](examples/tencent-ipv6.toml) | 腾讯云，单个 IPv6 子域名 |
| [`examples/aliyun-ipv4.toml`](examples/aliyun-ipv4.toml) | 阿里云，单个 IPv4 子域名 |
| [`examples/cloudflare-multi.toml`](examples/cloudflare-multi.toml) | Cloudflare，多子域名 + 根域名 |
| [`examples/huawei-ipv6.toml`](examples/huawei-ipv6.toml) | 华为云，IPv6 |
| [`examples/mixed-records.toml`](examples/mixed-records.toml) | 同一服务商，A + AAAA 混合多记录 |

### 例 1：最简——阿里云单个 IPv6 子域名

```toml
[ddns]
provider = "aliyun"
domain = "example.com"
sub_domain = "home"

[aliyun]
region = "cn-hangzhou"
```

```dotenv
ALIYUN_ACCESS_KEY_ID=LTAIxxxxxxxxxxxx
ALIYUN_ACCESS_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
```

效果：把 `home.example.com` 的 AAAA 记录更新为当前公网 IPv6。

### 例 2：腾讯云 + IPv4

```toml
[ddns]
provider = "tencent"
record_type = "A"
domain = "example.com"
sub_domain = "nas"
ttl = 600

[tencent]
```

```dotenv
TENCENT_ACCESS_KEY_ID=AKIDxxxxxxxxxxxx
TENCENT_ACCESS_KEY_SECRET=xxxxxxxxxxxxxxxx
```

### 例 3：Cloudflare 多子域名（含根域名）

```toml
[ddns]
provider = "cloudflare"
domain = "example.com"

[[records]]
sub_domain = "home"
record_type = "AAAA"

[[records]]
sub_domain = "www"
record_type = "A"

[[records]]
sub_domain = "@"          # 根域名 example.com
record_type = "A"

[cloudflare]
# zone_id = "023e105f4ecef8ad9ca31a8372d0c353"   # 可选，填了少一次查询
proxied = false
```

```dotenv
CLOUDFLARE_API_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxx
```

效果：一次运行同时维护 `home.example.com`(AAAA)、`www.example.com`(A)、`example.com`(A)。
AAAA 只探测一次、A 只探测一次，共两次探测。

### 例 4：华为云 IPv6

```toml
[ddns]
provider = "huawei"
domain = "example.com"
sub_domain = "home"

[huawei]
region = "cn-north-4"     # 必填
```

```dotenv
HUAWEI_ACCESS_KEY_ID=xxxxxxxxxxxx
HUAWEI_ACCESS_KEY_SECRET=xxxxxxxxxxxx
```

### 例 5：多域名 + A/AAAA 混合

```toml
[ddns]
provider = "aliyun"
check_interval = 120
log_level = "INFO"

[[records]]
domain = "example.com"
sub_domain = "home"
record_type = "AAAA"

[[records]]
domain = "example.com"
sub_domain = "vpn"
record_type = "A"
ttl = 60

[[records]]
domain = "other.com"
sub_domain = "@"
record_type = "AAAA"

[aliyun]
region = "cn-hangzhou"
```

### 例 6：同一 IP 同步到多个服务商（多实例）

一个进程只更新一个服务商。要同时同步到多家，用"每实例一个目录"：

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

密钥从**配置文件同级目录**的 `.env` 读取，状态文件也落在该目录，实例之间完全隔离：

```bash
DDNS_CONFIG=./ddns-instances/aliyun/ddns.toml     python -m ddns &
DDNS_CONFIG=./ddns-instances/cloudflare/ddns.toml python -m ddns &
DDNS_CONFIG=./ddns-instances/tencent/ddns.toml    python -m ddns &
```

> 默认读当前目录的 `ddns.toml`；用 `DDNS_CONFIG` 环境变量可指定任意路径。

## 运行

```bash
python -m ddns
# 安装后也可直接用命令
ddns
```

输出示例：

```
2026-10-03 09:40:00 INFO 启动 DDNS 监控 | 服务商: aliyun | 记录 2 条: home.example.com(AAAA), www.example.com(A)
2026-10-03 09:40:01 INFO home.example.com AAAA 变化: None -> 2409:8a1e:xxxx::1
2026-10-03 09:40:01 INFO DNS更新成功: home.example.com -> 2409:8a1e:xxxx::1
2026-10-03 09:40:02 INFO www.example.com A 变化: None -> 203.0.113.7
2026-10-03 09:40:02 INFO DNS更新成功: www.example.com -> 203.0.113.7
2026-10-03 09:41:00 INFO home.example.com AAAA 未变化: 2409:8a1e:xxxx::1
```

### 长期运行（systemd）

```ini
[Unit]
Description=DDNS (aliyun)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/ddns-instances/aliyun
Environment=DDNS_CONFIG=/opt/ddns-instances/aliyun/ddns.toml
ExecStart=/usr/bin/python3 -m ddns
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ddns@aliyun   # 若做成模板单元
sudo journalctl -u ddns -f                # 看日志
```

## 工作原理

1. **探测**：每种记录类型先本地 `socket` 连一个公网目标，读取内核选出的出口源地址（快）；再用外部 API 从公网侧回看校验。两者不一致以公网为准，外网 API 全挂时降级用本地结果。
2. **校验**：用 `ipaddress` 的 `is_global` 判定，丢弃私有 / 回环 / 链路本地 / ULA / CGNAT / 保留段地址。
3. **比对**：与状态文件中上次记录比较，相同则跳过（不调 API）。
4. **更新**：变化时调用所选服务商 API 更新记录，成功后写回状态。

## 常见问题

**Q：报错 `未找到 xxx 的 AAAA 记录，请先在控制台手动创建`**
本工具只更新已有记录，不会创建。请先在服务商控制台为 `子域名.主域名` 建一条同类型记录。

**Q：根域名怎么写？**
`sub_domain = "@"` 或直接留空 `sub_domain = ""`，两种等价。

**Q：切换服务商要做哪些改动？**
改 `ddns.toml` 的 `provider` 与对应 `[<provider>]` 段，并在 `.env` 填该服务商密钥；记得换装 SDK extra。

**Q：拿不到带 `::` 的公网 IPv6，或探测失败？**
先确认机器确有可用公网 IPv6（`curl -6 ifconfig.co` 或 `ping6 2400:3200::1`）。若系统设置了 HTTP 代理，本工具已通过 `trust_env=False` 忽略代理避免干扰。

**Q：日志里地址一直"未变化"？**
正常，说明 IP 稳定，未产生任何 API 调用。

**Q：多个实例共用一个状态文件会冲突吗？**
状态按 `provider:record_type:fqdn` 分键，不会互相误判；但并发写仍有竞态，建议每实例独立目录（默认即是）。

## 测试

```bash
python -m unittest discover -s tests -t .
# 或
pip install -e ".[dev]" && pytest
```

覆盖配置加载、地址校验、多 API 回退、探测降级、多记录扇出、状态读写，以及各服务商的记录解析 / 更新（含主机记录归一化）。**不需要真实密钥，也不发起真实请求**；未安装任何厂商 SDK 时核心测试仍全绿。

## 安全提示

- `.env` 含真实密钥，已在 `.gitignore` 忽略，**切勿提交**。
- `ddns.toml` 可能含 zone id 等隐私信息，同样已忽略；仅 `*.example` 模板入库。
- 状态文件 `ddns_state.json` 不入库。
- 建议使用仅授权 DNS 读写权限的最小权限凭据。

## 目录结构

```
ddns/
├── ddns/                  # 主包
│   ├── config.py          # ddns.toml + .env 解析
│   ├── ip.py              # 公网 IP 探测（v4/v6）
│   ├── state.py           # 状态持久化
│   ├── app.py             # 主循环与多记录扇出
│   ├── cli.py             # 命令行入口
│   └── providers/         # 各服务商实现
│       ├── base.py        # Target + BaseProvider
│       ├── tencent.py
│       ├── aliyun.py
│       ├── cloudflare.py
│       └── huawei.py
├── examples/              # 可直接复制的配置样例
├── tests/
├── ddns.toml.example
├── .env.example
└── pyproject.toml
```

## 许可证

[MIT](LICENSE)
