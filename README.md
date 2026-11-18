# 同济高等讲堂 · 自动报名工具（Windows&&Linux）

> 本项目基于 [marshw666/tongji-high-education-lecture](https://github.com/marshw666/tongji-high-education-lecture)
> 的 `tjh.py` 二次开发，补上了在 Windows 上长期挂机所需的全部能力。

一个给同济大学「高等讲堂」用的命令行报名工具：用你自己的微信登录态调学校接口，
可以查讲座、查资格、按报名开放时间卡点抢、以及盯着已报满的场次捡漏。

---

## 它解决什么问题

原版 `tjh.py` 已经能做单次卡点报名，但在 Windows 上长期挂着会遇到四个麻烦，这个项目
都处理了：

| 问题 | 这里的做法 |
| --- | --- |
| 站点只支持微信网页授权，桌面浏览器 F12 拿不到 cookie | 直接从**电脑微信**的 Chromium cookie 库（DPAPI + AES-GCM）解密提取，一条命令完成 |
| cookie 约 24 小时过期 | 自动检测微信库变化并续期，失效时安静等待而不是刷屏 |
| 想盯着「已报满 → 有人退」的场次 | 轮询「有余位」列表，名额一放出立即提交，日志标 `捡漏命中` |
| 高频轮询会被服务端限流 | 自适应降速：健康时 1 秒，连续失败自动降到 5 秒，30 分钟后试探提速 |

## 功能

- **零浏览器**：不需要打开网页，后台直接调接口
- **常驻守护**：注册成 Windows 计划任务，登录自启、崩溃 60 秒内自愈
- **卡点报名**：按服务端时钟校准，开放前 0.4 秒开始提交
- **捡漏**：已报满的讲座有人退，下一个轮询周期内就抢
- **按级别过滤**：默认只抢院级（`--level 2`），校级可关掉
- **黑名单**：`skip.txt` 里写 DataId，取消过的场次不会被抢回来
- **事后复核**：报名成功后 10 分钟复验一次，发现被回滚会记下来（不会自动重抢）
- **日志自管理**：超过 2MB 自动截断，被限流时指数退避

## 快速开始（Windows 10/11）

```bat
:: 1. 依赖（需要一个 Python 3.8+）
setup.cmd

:: 2. 取微信登录态（先在电脑微信里打开一次讲座页）
powershell -ExecutionPolicy Bypass -File refresh-cookie.ps1

:: 3. 确认能通
tjh.cmd doctor
tjh.cmd whoami
tjh.cmd list --status 1

:: 4. 挂起来
watch.cmd
```

常驻运行（计划任务）：

```bat
:: 以管理员身份运行一次
schtasks /Create /TN TJLectureWatcher /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"%~dp0watch-loop.ps1\"" /SC ONLOGON /F
```

## 命令

```bat
tjh.cmd doctor                 :: 自检：凭证是否有效
tjh.cmd whoami                 :: 姓名/学号/名单/人脸采集状态
tjh.cmd list --status 1        :: 有余位的
tjh.cmd list --status 3        :: 还没开放报名的
tjh.cmd signup <DataId>        :: 卡点报名
tjh.cmd cancel <DataId>        :: 取消报名

watch.cmd                      :: 常驻守护
watch.cmd --once --dry-run     :: 演练一轮，不提交
watch.cmd --level 2 --poll 1   :: 只抢院级、1 秒轮询
```

## 关于 cookie

站点的登录只能走微信网页授权，`PG.ASP.Session.ID` 就是你的登录凭证，**等价于账号密码**。

本项目从电脑微信的本地 Chromium cookie 库读取它：

```
%APPDATA%\Tencent\xwechat\radium\web\profiles\*\Network\Cookies
```

读取时需要用当前 Windows 用户的 DPAPI 密钥解密（Chromium 的 AES-GCM 方案），
提取结果只写到本机 `cookie.txt`，不会上传到任何地方。

`cookie.txt`、`token.txt`、`watch-state.json`、`skip.txt`、日志都已在 `.gitignore` 里，
不会被提交。

## 免责声明

- 这是**个人自用**工具。请只用自己的账号，不要代报、不要多开。
- 自动化脚本通常不被学校的使用条款允许，使用风险自负：账号受限、报名被撤销等后果与作者无关。
- 报名后请按时出勤。缺勤会记「未签到」，很多学校有次数限制。
- 接口随时可能变更。报错先跑 `tjh.cmd doctor` 看原始响应。

## 许可

`tjh.py` 及其相关逻辑来自上游项目，上游仓库**未声明开源许可证**（描述为
"Personal use only"）。本仓库仅以个人学习与研究为目的做二次开发与整合，
不主张对上游代码的任何额外授权。如需商用或再分发，请先联系原作者。

本仓库新增部分（`watch.py`、`refresh-cookie.ps1`、`tools/` 等）同样仅供个人使用。
