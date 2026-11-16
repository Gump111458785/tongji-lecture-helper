# tjh.py 使用说明（Python 版）
你是否还在为同济大学高等讲堂抢不到课而发愁，这个脚本会教会你如何快速自动化抢讲座。
讲解一下这个 `tjh.py` 如何使用。

---

## 1. 这是什么

一个命令行工具，用你浏览器里的登录态（cookie）调用同济高等讲堂的接口，可以：

- 查身份、查资格
- 列出讲座、看详情
- **按报名开放时间卡点自动报名**
- 取消报名

不需要开浏览器，可以挂后台、写定时任务。

**前提**：Python 3.8+，装了 `requests`。

```bash
python3 -V
python3 -m pip install requests
```

---

## 2. 准备凭证

这个站点**没有 `token` 请求头**，认证完全靠 `PG.ASP.Session.ID` 这个 cookie。所以要复制 cookie，不是 token。

### 2.1 从浏览器复制

1. Chrome 打开 `https://lecture.tongji.edu.cn/wxpage/index`，确认已登录（能看到讲座列表）
2. F12 → **Network** → 筛选 `api/gj`
3. 随便点一个请求 → **Headers** → **Request Headers**
4. 找到 `Cookie:` 那一行，**整行复制**

形如：

```
PG.ASP.Session.ID=30d77657-5bf0-427e-9672-6c579422b488; PG.ASP.WeiXinCode.ID=be0b112892ea40bea22dd31e7ae51139
```

> 两个 cookie 都要。只复制一个大概率 500。

### 2.2 三种保存方式（选一种）

**方式 A：环境变量**（推荐，当前终端有效）

```bash
export TJH_COOKIE='PG.ASP.Session.ID=...; PG.ASP.WeiXinCode.ID=...'
```

**方式 B：参数**（一次性）

```bash
python3 tjh.py --cookie 'PG.ASP.Session.ID=...; PG.ASP.WeiXinCode.ID=...' whoami
```

**方式 C：文件**（推荐，长期用）

在 `tjh.py` 同目录建 `cookie.txt`，把整行粘进去：

```bash
echo 'PG.ASP.Session.ID=...; PG.ASP.WeiXinCode.ID=...' > cookie.txt
python3 tjh.py whoami
```

脚本自动按 `--cookie` → `TJH_COOKIE` → `cookie.txt` 的顺序找。

### 2.3 关于 token

`--token` / `TJH_TOKEN` / `token.txt` 仍然保留，但**当前部署用不上**——浏览器里根本没有这个头。除非哪天学校改了鉴权方式。

### 2.4 全局参数

| 参数 | 说明 |
| --- | --- |
| `--cookie '...'` | 整串 cookie |
| `--token '...'` | token（本站用不到） |
| `--ua '...'` | 自定义 User-Agent，默认手机微信 UA |
| `-v` / `--verbose` | 打印请求细节 |

---

## 3. 命令总览

```bash
python3 tjh.py <命令> [参数]
```

| 命令 | 作用 |
| --- | --- |
| `doctor` | 自检：打印实际发出的请求头和响应，排查 500 |
| `whoami` | 查当前登录身份 |
| `check [DataId]` | 资格自检：能不能报名 |
| `list` | 列出讲座 |
| `detail <DataId>` | 看讲座详情（原始 JSON） |
| `signup <DataId>` | 卡点报名 |
| `cancel <DataId>` | 取消报名 |

---

## 4. 命令详解

### 4.1 `doctor` —— 连不上先跑这个

```bash
python3 tjh.py doctor
```

输出：

```
=== 凭证 ===
  token        : 未设置
  cookie 数量  : 2
    - PG.ASP.Session.ID = 30d77657-5bf...（36 字符）
    - PG.ASP.WeiXinCode.ID = be0b112892e...（32 字符）
  User-Agent   : Mozilla/5.0 (iPhone; ...) MicroMessenger/8.0.40
  Authorization: Basic cTN4YXRwbTV0eHc0Mm...

=== 试请求 https://lecture.tongji.edu.cn/api/gj/studentwx/studentapi/StudentInfo ===
  HTTP 200
  实际发送的 Cookie: PG.ASP.Session.ID=...; PG.ASP.WeiXinCode.ID=...
  实际发送的 token : (无)
  响应体: {"state":"success","data":{"Name":"张三",...}}

√ 认证成功，可以正常使用。
```

失败时会给具体原因（cookie 过期、漏了 cookie、UA 不匹配等）。

---

### 4.2 `whoami` —— 查身份

```bash
python3 tjh.py whoami
```

```
姓名     : 张三
学号     : 2131234
学院     : 电子与信息工程学院
专业     : 信息与通信工程
培养层次 : 硕士研究生
在可报名名单内 : True
已完成人像采集 : True
```

这两个布尔值决定你能不能报名，见下一节。

---

### 4.3 `check` —— 资格自检

```bash
# 只查账号层面
python3 tjh.py check

# 加上具体讲座
python3 tjh.py check d1b331dcaff0843e8c980a9335e525ce
```

输出：

```
=== 资格自检 ===
[✓] 登录态        张三 / 2131234
[✓] 在可报名名单   是
[✓] 人像采集       已完成
[✓] 人脸校验接口   通过
[ ] 讲座           人工智能与城市治理
[·] 报名状态       3 未开始报名
[ ] 报名开放       2026-11-06T12:00:00
[✓] 是否已报名     未报名
[⏳] 结论          未到开放时间（2026-11-06T12:00:00），可用 signup 卡点
```

符号含义：

| 符号 | 含义 |
| --- | --- |
| `[✓]` | 通过 |
| `[✗]` | 不通过，会拦住报名 |
| `[!]` | 需要注意（已报过 / 查不到） |
| `[⏳]` | 还没到时间，正常 |
| `[·]` | 中性信息 |

**报名的三个硬门槛**（任一为 ✗ 就别浪费时间抢）：

1. 登录态有效
2. `在可报名名单` = 是（名单由学院维护，脚本绕不过）
3. `人像采集` / `人脸校验接口` = 通过（要去微信端或一体机采集）

---

### 4.4 `list` —— 找讲座

```bash
python3 tjh.py list                       # 全部
python3 tjh.py list --status 3            # 未开始报名
python3 tjh.py list --status 1            # 有余位
python3 tjh.py list --time 1 --level 1    # 当月 + 校级
python3 tjh.py list --json                # 原始 JSON
```

输出：

```
DataId       状态           报名开放             讲座时间          标题
--------------------------------------------------------------------------------
d1b331dca... 未开始报名     2026-11-06T12:00:00  2026-11-07 14:00  人工智能与城市治理
a2c44f1b9... 有余位         2026-11-03T09:00:00  2026-11-04 19:00  碳中和与能源转型

共 3 页，当前第 1 页
```

参数：

| 参数 | 取值 |
| --- | --- |
| `--status` | `0` 全部 / `1` 有余位 / `2` 已报满 / `3` 未开始 / `4` 已结束 |
| `--time` | `0` 全部 / `1` 当月 / `2` 往期 |
| `--level` | `0` 全部 / `1` 校级 / `2` 院级 |
| `--page` / `--page-size` | 分页，默认 1 / 20 |

第一列 `DataId` 就是后面要用的 ID。

---

### 4.5 `detail` —— 看详情

```bash
python3 tjh.py detail d1b331dcaff0843e8c980a9335e525ce
```

输出原始 JSON（字段很多），重点看：

| 字段 | 含义 |
| --- | --- |
| `Cathedra` | 讲座标题 |
| `LectureTimeStart` | 讲座开始时间 |
| `TimeSigningUp` | **报名开放时间**（`signup` 按这个卡点） |
| `LectureHallStatus` | 1 有余位 / 2 已满 / 3 未开始 / 4 已结束 |
| `XSSigningUp` | 你已报名的时间，有值就别重复报 |
| `Capacity` / `Venue` | 容量 / 地点 |

---

### 4.6 `signup` —— 卡点报名

```bash
python3 tjh.py signup d1b331dcaff0843e8c980a9335e525ce
```

默认行为：读 `TimeSigningUp`，**提前 0.4 秒开始**，每秒尝试约 4 次，最多坚持 180 秒。

输出：

```
讲座：人工智能与城市治理
  DataId      : d1b331dcaff0843e8c980a9335e525ce
  状态        : 3 未开始报名
  讲座时间    : 2026-11-07T14:00:00
  报名开放    : 2026-11-06T12:00:00
  已报名时间  : 未报名
  当前身份    : 张三 / 2131234
  目标时刻    : 2026-11-06 12:00:00（服务端时钟）
  等待 3521.4s ...
[12:00:00.412] #1 未成功：报名尚未开始
[12:00:00.688] #2 已受理，查询结果 ...
√ 报名成功（服务端时间 2026-11-06T12:00:01）
```

参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--at '2026-11-06 12:00:00'` | 用 `TimeSigningUp` | 手动指定开抢时刻（北京时间） |
| `--now` | 关 | 不等待，立刻尝试一次（已开放的讲座用） |
| `--lead 0.4` | `0.4` | 提前多少秒开始 |
| `--patience 180` | `180` | 开抢后最多坚持多少秒 |
| `--interval 0.25` | `0.25` | 每次尝试间隔秒数 |
| `--dry-run` | 关 | 只做检查，不提交 |

常见用法：

```bash
# 已经开放了，马上抢
python3 tjh.py signup <DataId> --now

# 手动指定时间（比如 TimeSigningUp 字段为空）
python3 tjh.py signup <DataId> --at '2026-11-06 12:00:00'

# 先演练，不真报
python3 tjh.py signup <DataId> --dry-run

# 抢不到就多坚持一会儿
python3 tjh.py signup <DataId> --patience 300 --interval 0.2
```

**它是怎么抢的**（也是为什么成功率比手点高）：

1. 用 HTTP `Date` 头校准服务端时钟，不依赖你电脑的时间
2. 每次尝试前重新调 `SetCredentials` 现签一个报名凭证（`code` 有时效，不能复用）
3. 用 `SginInLectureHallCredentials` 提交
4. 提交后轮询 `GetSginInTime` 直到出结果（成功 / 失败）

> 别把 `--interval` 调到 0.05 以下。服务端是异步队列，刷再快也不会更靠前，只会被 WAF 盯上。

---

### 4.7 `cancel` —— 取消报名

```bash
python3 tjh.py cancel d1b331dcaff0843e8c980a9335e525ce
```

```
√ 已取消报名
```

只能取消**还没开始**的讲座（开讲后取消不了，前端也是这么限制的）。

---

## 5. 典型流程

**第一次用：**

```bash
export TJH_COOKIE='PG.ASP.Session.ID=...; PG.ASP.WeiXinCode.ID=...'

python3 tjh.py doctor        # 1. 确认 cookie 有效
python3 tjh.py whoami        # 2. 看身份
python3 tjh.py list --status 3   # 3. 找 DataId
python3 tjh.py check <DataId>    # 4. 确认有资格
python3 tjh.py signup <DataId>   # 5. 挂上等开抢
```

**抢完确认：**

```bash
python3 tjh.py check <DataId>    # 看"是否已报名"是否有时间
```

**脚本串联：**

```bash
ID=d1b331dcaff0843e8c980a9335e525ce
python3 tjh.py check "$ID" && python3 tjh.py signup "$ID"
```

---

## 6. 退出码

| 码 | 含义 | 典型场景 |
| --- | --- | --- |
| `0` | 成功 / 有资格 | 报名成功、`check` 通过 |
| `1` | 失败 | 已满、已结束、超时未抢到 |
| `2` | 参数或资格问题 | 不在名单、没人脸、DataId 不对 |
| `3` | 凭证失效 | cookie 过期，重新复制 |

`3` 是唯一需要你动手的：回浏览器重新复制 cookie。

---

## 7. 排错

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `× 缺少凭证` | 没设 cookie | `export TJH_COOKIE=...` 或建 `cookie.txt` |
| `HTTP 500` + 空响应 | cookie 失效/不全 | 跑 `doctor`，重新复制整行 cookie |
| `HTTP 404` | 接口下线（如 `SginInLectureHall`） | 正常现象，脚本已不走那条 |
| `HTTP 200` + 空 body | 请求方法用错 | 不是成功，检查命令 |
| `× 不在"高等讲堂可报名名单"内` | 名单没你 | 找学院教务加名单，脚本绕不过 |
| `× 未完成人脸采集` | 没做人像采集 | 微信端/一体机采集一次 |
| `× 名额已满` | 被抢光了 | 等别人取消，或换一场 |
| `× 超时未成功` | 一直返回"未开始" | 检查系统时间/时区，或加大 `--patience` |
| 中文乱码 | 终端编码 | `export PYTHONIOENCODING=utf-8` |

排查顺序：`doctor` → `whoami` → `check` → `list` → `signup`。

---

## 8. 定时任务（可选）

`signup` 自己会等到开放时间，所以 cron 只要**提前几分钟**启动就行：

```cron
# 每天 11:55 跑一次，抢 12:00 开放的讲座
55 11 * * * cd /path/to/tj-lecture && /usr/bin/python3 tjh.py signup 20261106001 >> signup.log 2>&1
```

注意：

- cron 环境没有你 shell 里的 `TJH_COOKIE`，用 `cookie.txt` 文件方式最稳
- cookie 会过期（几小时到几天不等），过期后 cron 会一直失败，需要手动更新
- 日志里看 `√ 报名成功` / `×` 判断结果

---

## 9. 安全提醒

1. **cookie 等于你的账号密码**。`PG.ASP.Session.ID` 泄露 = 别人能替你报名、取消。别提交到 Git，别发群里。
2. **只给自己用**。多账号代报属于违规，学校能通过学号 + IP + UA 查出来。
3. **控制频率**。默认参数已经比人手快很多，别改成死循环。
4. **别占坑**。报名了不去会被记"未签到"，很多学校有次数限制。
5. 接口随时可能变，报错先跑 `doctor` 看原始响应。
