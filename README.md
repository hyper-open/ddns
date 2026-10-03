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
| `update_policy` | | `exact` 或 `stable`（见「[更新策略](#更新策略update_policy)」） | `exact` |
| `state_file` | | 状态文件路径 | 本文件同目录 `ddns_state.json` |
| `domain` | | 默认主域名 | `example.com` |
| `sub_domain` | | 默认主机前缀；根域名用 `@` 或留空 | 空 |
| `record_type` | | 默认记录类型 `A` / `AAAA` | `AAAA` |
| `ttl` | | 默认 TTL（秒） | `600` |
| `source` | | 默认出口：源 IP 或网卡名（多上行时用） | 空（走默认路由） |

`[[records]]` 每条记录可写：`domain`、`sub_domain`、`record_type`、`ttl`、`source`，未写的从 `[ddns]` 继承。

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
| [`examples/multi-egress.toml`](examples/multi-egress.toml) | 多上行，把不同出口 IP 写到不同子域名 |

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

### 例 7：多出口 IP（多上行分写不同域名）

一台机器有多个公网出口（多网卡 / 多拨 / 多上行）时，给每条记录配 `source`，
探测会**强制从该出口发包**，从而把每个出口各自的公网 IP 写到对应子域名。

```toml
[ddns]
provider = "aliyun"
domain = "example.com"

[[records]]
sub_domain = "home1"
record_type = "AAAA"
source = "eth0"              # 网卡名，自动解析为该网卡的 IPv6

[[records]]
sub_domain = "home2"
record_type = "AAAA"
source = "2001:db8::10"      # 直接给源地址

[[records]]
sub_domain = "backup"
record_type = "A"
source = "pppoe-wan"         # PPPoE 拨号出口

[[records]]
sub_domain = "default"
record_type = "AAAA"         # 不写 source：走默认路由
```

**`source` 取值**

| 写法 | 说明 |
| --- | --- |
| 留空 / 不写 | 走默认路由（与原行为一致） |
| 源 IP，如 `192.168.1.2`、`2001:db8::10` | 跨平台、最精确，推荐 |
| 网卡名，如 `eth0`、`pppoe-wan`、`wlan0` | 自动解析该网卡的地址；依赖 `psutil` |

**要点**

- 源 IP 的地址族必须与 `record_type` 匹配（`A` 用 IPv4，`AAAA` 用 IPv6），否则启动即报错。
- 网卡名在 Linux 是接口名（`eth0`/`pppoe-wan`），Windows 是系统连接名（`以太网`、`WLAN`）；
  多网卡多地址时取该地址族第一个非链路本地地址，需精确指定请直接写源 IP。
- 同一 `(记录类型, 出口)` 每轮**只探测一次**，相同出口的多条记录复用结果：
  上面 `home1`(eth0) 与 `default`(默认路由) 各探测一次，互不影响。
- 出口地址写在探测 socket 上（本地探测 `bind`，公网 API 经带源地址的 HTTP 连接），
  因此返回的是**该出口真实对外的公网 IP**，即使多出口共享同一默认路由也能区分。

### 关于 IPv6 稳定地址与临时地址

开启 IPv6 隐私扩展（RFC 4941，现代系统默认开启）时，一个网卡会有**多个全局 IPv6**，
共享同一个 /64 前缀，只有后 64 位不同：

```
inet6 2409:8a1e:991c:c4b0:3f:abb5:22f6:483e  autoconf secured              ← 稳定地址（不随时间变）
inet6 2409:8a1e:991c:c4b0:203d:e8ab:9e01:f7eb  deprecated autoconf temporary ← 旧临时地址（已弃用）
inet6 2409:8a1e:991c:c4b0:eca8:8231:7682:a471  autoconf temporary            ← 当前临时地址
```

- **临时地址**默认每天轮换（`temppltime=86400`），7 天后彻底过期（`tempvltime=604800`），
  旧地址会短暂以 `deprecated` 状态共存，所以会看到"多个"。
- 系统在对外主动连接时**优先使用临时地址**（`prefer_tempaddr=1`）。
- 因此内核默认会选到临时地址，随轮换变化；而 **DNS 记录变更存在传播延迟**，
  频繁变更不是我们想要的。

> **本工具会自动优先稳定地址**（Linux / macOS）：探测到全局 IPv6 后，若存在**同 /64 前缀**
> 的稳定地址，则改用它，从源头避免轮换导致的 DNS 更新。显式把 `source` 写成具体 IP 时
> **尊重用户选择，不做替换**。Windows 暂不支持识别稳定地址，行为与原先一致。
> 系统若无法识别稳定地址（如只启用了临时地址），会回退到探测结果。
> 若要稳定解析，请**显式把稳定地址写入 `source`**。

**查询稳定地址**（排除带 temporary 标志的地址）：

```bash
# macOS
ifconfig en0 | grep 'inet6.*autoconf' | grep -v temporary

# Linux
ip -6 addr show dev eth0 | grep 'scope global' | grep -v temporary
```

**查询临时地址**（Linux / macOS 通用，`temporary` 标记）：

```bash
# macOS，只看临时地址
ifconfig en0 | grep 'inet6.*temporary'

# Linux，只看临时地址
ip -6 addr show dev eth0 | grep 'scope global' | grep temporary
```

**Windows（PowerShell）**

```powershell
Get-NetIPAddress -AddressFamily IPv6 |
  Where-Object { $_.IPAddress -notlike 'fe80*' } |
  Format-Table IPAddress, PrefixOrigin, SuffixOrigin, ValidLifetime, PreferredLifetime
```

Windows 的 `SuffixOrigin` 为 `Random` 表示临时地址，`Stable`/`EUI64` 表示稳定地址。

拿到稳定地址后写进配置：

```toml
[[records]]
sub_domain = "home"
record_type = "AAAA"
source = "2409:8a1e:991c:c4b0:3f:abb5:22f6:483e"   # 稳定地址，不随临时地址轮换
```

> 注意：稳定地址的**前三段（/64 前缀）**在运营商重新分配时仍会变化，这属于拨号/租约层面，
> 无法通过 `source` 规避；此时写死 `source` 反而会失效，可改用网卡名或不指定。
> 也可关闭隐私扩展让系统只用稳定地址（**全局生效**，请自行评估）：
> macOS `sudo sysctl -w net.inet6.ip6.use_tempaddr=0`；
> Linux `sudo sysctl -w net.ipv6.conf.eth0.use_tempaddr=0`。

### 更新策略（`update_policy`）

「优先稳定地址」解决的是"**能从源头拿到不轮换的地址**"；当系统只有临时地址可用时，
还有一层兜底——**同前缀不更新**，避免临时地址轮换引起的无谓更新。

| 取值 | 行为 |
| --- | --- |
| `exact`（默认） | IP 变了就更新 |
| `stable` | IPv6 新旧地址**同 /64** 且**旧地址仍在本机**时，跳过更新 |

```toml
[ddns]
update_policy = "stable"
```

**为什么是"且旧地址仍在本机"这个条件**：如果只按"同前缀就跳过"，一旦旧临时地址彻底过期，
DNS 会**永久指向一个失效地址**。加上"旧地址仍存在"的判断后：

- 临时地址轮换、旧地址仍处于 `deprecated`（7 天内）→ **跳过**，DNS 不变，无抖动
- 旧地址彻底过期消失 → **条件不成立，正常更新**，DNS 自愈
- 前缀变化（运营商重分配 / 拨号换 IP）→ 正常更新

仅对 `AAAA`（IPv6）生效；IPv4 无临时地址轮换，且用 /24 判断会误跳过不同主机的变化。
默认 `exact`，不改变现有行为。

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

## 长期运行

本工具是常驻循环进程，需交给系统服务管理器托管，实现开机自启、崩溃重拉、日志留存。

先在终端确认 Python 绝对路径（自启服务不继承你的 shell 环境，必须写全路径）：

```bash
# macOS / Linux
command -v python3        # 例：/usr/local/bin/python3
# Windows (PowerShell / CMD)
where python              # 例：C:\Python311\python.exe
```

> 下面以单实例（阿里云）为例，目录统一用 `<实例目录>` 表示，请替换成你的真实路径，
> 例如 Linux `/opt/ddns-instances/aliyun`、macOS `/Users/yourname/ddns-instances/aliyun`、
> Windows `C:\ddns-instances\aliyun`。多实例就照抄多份、改 `DDNS_CONFIG` 与目录名。

### Linux（systemd）

适用于大多数发行版（Debian/Ubuntu/CentOS/NAS 等）。推荐做成**模板单元**，一个文件跑多个实例。

`/etc/systemd/system/ddns@.service`：

```ini
[Unit]
Description=DDNS (%i)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/ddns-instances/%i
Environment=DDNS_CONFIG=/opt/ddns-instances/%i/ddns.toml
ExecStart=/usr/local/bin/python3 -m ddns
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用与查看：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ddns@aliyun        # @ 后是实例目录名
systemctl status ddns@aliyun
journalctl -u ddns@aliyun -f                  # 实时日志
```

> 若不想用 root，可放到 `~/.config/systemd/user/ddns@.service`，用
> `systemctl --user enable --now ddns@aliyun`，并 `loginctl enable-linger $USER` 让用户服务在未登录时也运行。

### macOS（launchd）

创建 `~/Library/LaunchAgents/com.example.ddns.aliyun.plist`（Label 每个实例唯一）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.example.ddns.aliyun</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>-m</string>
        <string>ddns</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/yourname/ddns-instances/aliyun</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>DDNS_CONFIG</key>
        <string>/Users/yourname/ddns-instances/aliyun/ddns.toml</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/yourname/ddns-instances/aliyun/ddns.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/yourname/ddns-instances/aliyun/ddns.err.log</string>
</dict>
</plist>
```

加载与管理：

```bash
# 加载（现代写法，macOS 10.13+）
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.ddns.aliyun.plist

# 查看状态 / 日志
launchctl list | grep ddns
tail -f ~/ddns-instances/aliyun/ddns.log

# 停止 / 卸载
launchctl bootout gui/$(id -u)/com.example.ddns.aliyun

# 改了 plist 后重新加载
launchctl bootout gui/$(id -u)/com.example.ddns.aliyun 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.ddns.aliyun.plist
```

> 注意：macOS 上自启服务**不会读取你的 shell 配置**（`.zshrc`/`.bash_profile`），
> 所以 `DDNS_CONFIG`、Python 路径都必须写绝对路径，不能依赖 PATH 或别名。
> 用 Homebrew 装的 Python 路径通常是 `/usr/local/bin/python3`（Intel）或 `/opt/homebrew/bin/python3`（Apple Silicon）。

### Windows（任务计划程序）

Windows 无 systemd，用**任务计划程序**以"无论用户是否登录"方式常驻。推荐先写一个启动脚本
`C:\ddns-instances\aliyun\run.bat`：

```bat
@echo off
set DDNS_CONFIG=C:\ddns-instances\aliyun\ddns.toml
cd /d C:\ddns-instances\aliyun
"C:\Python311\python.exe" -m ddns >> ddns.log 2>&1
```

注册开机任务（管理员 CMD）：

```bat
schtasks /Create /TN "DDNS-aliyun" ^
  /TR "C:\ddns-instances\aliyun\run.bat" ^
  /SC ONSTART /RU SYSTEM /RL HIGHEST /F
```

管理：

```bat
schtasks /Run    /TN "DDNS-aliyun"
schtasks /Query  /TN "DDNS-aliyun" /V /FO LIST
schtasks /Delete /TN "DDNS-aliyun" /F
```

> `/RU SYSTEM` 以系统账户运行，不弹窗、不要求登录；若日志要写到用户目录或用用户级凭据，
> 改成 `/RU 你的用户名 /RP 密码`。
> 图形界面里对应设置是：触发器"启动时"、勾选"不管用户是否登录都要运行"、勾选"如果任务失败，按以下频率重新启动"。

**可选：注册成真正的 Windows 服务**（崩溃自动重启，无需登录）。用 [NSSM](https://nssm.cc/)：

```bat
nssm install DDNS-aliyun "C:\Python311\python.exe" "-m ddns"
nssm set DDNS-aliyun AppDirectory "C:\ddns-instances\aliyun"
nssm set DDNS-aliyun AppEnvironmentExtra DDNS_CONFIG=C:\ddns-instances\aliyun\ddns.toml
nssm set DDNS-aliyun AppStdout "C:\ddns-instances\aliyun\ddns.log"
nssm set DDNS-aliyun AppStderr "C:\ddns-instances\aliyun\ddns.err.log"
nssm start DDNS-aliyun
```

### 三平台对照

| | Linux | macOS | Windows |
| --- | --- | --- | --- |
| 托管方式 | systemd | launchd | 任务计划程序 / NSSM |
| 配置文件位置 | `/etc/systemd/system/ddns@.service` | `~/Library/LaunchAgents/*.plist` | `schtasks` / 服务 |
| 开机自启 | `systemctl enable` | `launchctl bootstrap` | `/SC ONSTART` |
| 崩溃重拉 | `Restart=always` | `KeepAlive=true` | 任务计划"失败时重启" / NSSM |
| 看日志 | `journalctl -u` | `tail *.log` | 任务历史 / `*.log` |
| 不依赖登录 | 系统级自带 | 系统级自带 | `/RU SYSTEM` 或 NSSM |

**共同注意点**

- 自启服务不继承交互式 shell 环境，**Python 路径、`DDNS_CONFIG` 一律写绝对路径**。
- 每个实例用独立目录、独立 `DDNS_CONFIG`，避免状态文件并发写。
- 首次部署后先手动 `python -m ddns` 跑通，确认能取到正确 IP、能更新记录，再交给服务管理器。

## 工作原理

1. **探测**：每种记录类型先本地 `socket` 连一个公网目标，读取内核选出的出口源地址（快）；再用外部 API 从公网侧回看校验。两者不一致以公网为准，外网 API 全挂时降级用本地结果。记录若配了 `source`，则先 `bind`/挂源地址适配器，强制从指定出口发包。
2. **优选稳定地址**：IPv6 探测结果若存在同 /64 的稳定地址（Linux/macOS 可识别），改用它，避免隐私扩展临时地址轮换；显式指定源 IP 时不替换。
3. **校验**：用 `ipaddress` 的 `is_global` 判定，丢弃私有 / 回环 / 链路本地 / ULA / CGNAT / 保留段地址。
4. **比对**：与状态文件中上次记录比较，相同则跳过（不调 API）。探测结果按 `(记录类型, 出口)` 缓存，同出口只探测一次。`update_policy="stable"` 时，IPv6 同 /64 且旧地址仍在本机也跳过。
5. **更新**：变化时调用所选服务商 API 更新记录，成功后写回状态。

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
