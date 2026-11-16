#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同济高等讲堂 · 常驻自动报名守护进程

策略
----
* 每 `--poll` 秒拉一次「有余位」列表：正在报名的直接抢；已报满的讲座一旦有人
  取消，会重新出现在这个列表里，于是被顺手捡漏。
* 每 `--slow-poll` 秒拉一次「未开始报名」列表；进入 `--arm` 秒窗口后按服务端
  时钟准点提交。
* 服务端若返回「不在当前讲座报名范围内」（院级讲座限定本院、或不在名单），
  该讲座直接标记 `out_of_scope` 永久跳过，不再浪费请求。
* 状态写进 `watch-state.json`，重启不重复报名。
* 凭证失效时调用 refresh-cookie.ps1 自动续期。

用法
----
    watch.cmd                      # 常驻
    watch.cmd --once --dry-run     # 只跑一轮，不提交，看会抢什么
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from tjh import (  # noqa: E402
    CN_TZ,
    DONE_WORDS,
    ENDED_WORDS,
    FULL_WORDS,
    LIST_WORDS,
    NOT_START_WORDS,
    ApiError,
    TjLecture,
    TokenExpired,
    parse_time,
)

STATE_FILE = ROOT / "watch-state.json"
LOG_FILE = ROOT / "watch.log"
SKIP_FILE = ROOT / "skip.txt"
LOG_MAX_BYTES = 2_000_000
LOG_KEEP_LINES = 3000

TERMINAL = {"registered", "out_of_scope", "ended", "no_qualification", "cancelled"}
SCOPE_WORDS = ("不在当前讲座报名范围内", "不在报名范围", "无报名资格", "不具备", "不在名单")
# 出现这些字样说明登录态没了（401 nologin），必须走续期，不能当普通网络错误重试
AUTH_HINTS = ("401", "nologin", "未登录", "登录超时", "登录态失效")

log = logging.getLogger("watch")


def trim_log() -> None:
    """日志超过 2MB 就只保留最近 3000 行，避免长期跑把盘塞满。"""
    try:
        if not LOG_FILE.exists() or LOG_FILE.stat().st_size <= LOG_MAX_BYTES:
            return
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-LOG_KEEP_LINES:]
        LOG_FILE.write_text("\n".join(tail) + "\n", encoding="utf-8")
    except OSError:
        pass


def setup_logging() -> None:
    trim_log()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.setLevel(logging.INFO)
    log.handlers = [fh, sh]


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("状态文件损坏，重新开始")
    return {"lectures": {}, "counters": {}}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def acquire_single_instance():
    """文件锁保证只有一个实例（进程退出时锁自动释放）。"""
    try:
        import msvcrt
    except ImportError:
        return None
    fh = open(ROOT / "watch.lock", "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("已有 watch.py 实例在运行，本次退出", file=sys.stderr)
        raise SystemExit(0)
    return fh


def read_credential(name: str, env_name: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    path = ROOT / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def make_api(args: argparse.Namespace) -> TjLecture:
    token = read_credential("token.txt", "TJH_TOKEN")
    cookie = read_credential("cookie.txt", "TJH_COOKIE")
    if not token and not cookie:
        raise SystemExit("× 没有凭证：先跑 refresh-cookie.ps1 或填写 cookie.txt")
    return TjLecture(token=token, cookie=cookie, ua=args.ua or "", verbose=args.verbose)


def fetch_all(
    api: TjLecture,
    status: int,
    time_filter: int,
    class_level: int = 0,
    max_pages: int = 12,
) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while True:
        payload = api.list_lectures(
            page=page,
            page_size=50,
            status=status,
            time_filter=time_filter,
            class_level=class_level,
        )
        data = payload.get("data") or {}
        batch = data.get("row") or []
        rows.extend(batch)
        total = int(data.get("totalPage") or 1)
        if page >= total or page >= max_pages or not batch:
            break
        page += 1
    return rows


def is_scope_error(text: str) -> bool:
    return any(word in text for word in SCOPE_WORDS)


def is_auth_error(text: str) -> bool:
    return any(hint in text for hint in AUTH_HINTS)


def grab(
    api: TjLecture,
    data_id: str,
    args: argparse.Namespace,
    target_ts: float | None = None,
) -> tuple[str, str]:
    """抢一场讲座。返回 (结果, 说明)。

    结果: registered / out_of_scope / full / ended / not_open / error / timeout / dry_run
    """
    if target_ts is not None:
        while True:
            remain = target_ts - api.now()
            if remain <= 0:
                break
            time.sleep(min(remain, 30.0))

    deadline = api.now() + (args.patience if target_ts is not None else args.now_patience)
    attempt = 0
    while api.now() < deadline:
        attempt += 1
        try:
            code = api.set_credentials(data_id)
        except TokenExpired:
            raise
        except ApiError as exc:
            text = str(exc)
            if is_scope_error(text):
                return "out_of_scope", text
            if any(w in text for w in NOT_START_WORDS):
                time.sleep(args.interval)
                continue
            log.warning("取报名凭证失败（第 %d 次）：%s", attempt, text)
            return "error", text

        if args.dry_run:
            return "dry_run", f"第 {attempt} 次：拿到报名凭证，dry-run 未提交"

        try:
            resp = api.signup_with_code(code)
        except TokenExpired:
            raise
        except ApiError as exc:
            return "error", str(exc)

        state = resp.get("state")
        msg = str(resp.get("msg") or "")
        if state == "success":
            ok, text = api.wait_signup_result(data_id)
            return ("registered" if ok else "unknown"), text
        if any(w in msg for w in DONE_WORDS):
            return "registered", msg
        if any(w in msg for w in LIST_WORDS):
            return "out_of_scope", msg
        if any(w in msg for w in FULL_WORDS):
            return "full", msg
        if any(w in msg for w in ENDED_WORDS):
            return "ended", msg
        if any(w in msg for w in NOT_START_WORDS):
            time.sleep(args.interval)
            continue
        return "error", msg or str(resp)

    return "timeout", f"共尝试 {attempt} 次仍未成功"


def load_skip() -> set[str]:
    """skip.txt：一行一个 DataId，# 开头为注释。取消过的场次写进来就不会再抢。"""
    if not SKIP_FILE.exists():
        return set()
    ids = set()
    for line in SKIP_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ids.add(line)
    return ids


SKIPS: set[str] = set()
SKIP_MTIME = 0.0


def refresh_skips() -> None:
    """skip.txt 改了就重新加载，不用重启。"""
    global SKIPS, SKIP_MTIME
    try:
        mtime = SKIP_FILE.stat().st_mtime
    except OSError:
        SKIPS = set()
        return
    if mtime != SKIP_MTIME:
        SKIP_MTIME = mtime
        SKIPS = load_skip()
        log.info("skip.txt 已加载 %d 条", len(SKIPS))


def handle_row(api: TjLecture, row: dict, args: argparse.Namespace, state: dict) -> None:
    data_id = str(row.get("DataId"))
    title = row.get("Cathedra") or ""
    status = row.get("LectureHallStatus")
    rec = state["lectures"].get(data_id) or {}

    if data_id in SKIPS:
        return
    # 级别过滤兜底：列表行若带 ClassLevel，直接按它判断，防止接口忽略筛选参数
    level = row.get("ClassLevel")
    if args.level and level is not None:
        try:
            if int(level) != args.level:
                return
        except (TypeError, ValueError):
            pass
    if rec.get("result") in TERMINAL:
        return
    if time.time() - float(rec.get("last_try") or 0) < args.retry_gap:
        return

    target_ts = None
    if status == 1:
        today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
        used = state.get("counters", {}).get(today, 0)
        if args.max_per_day and used >= args.max_per_day:
            log.info("今日已报 %d 场，达上限，跳过《%s》", used, title)
            return
        if rec.get("result") == "full":
            log.info("捡漏命中：《%s》%s 刚放出名额，立刻抢", title, data_id)
        else:
            log.info("发现开放报名：《%s》%s", title, data_id)
    elif status == 3:
        open_at = parse_time(row.get("TimeSigningUp"))
        if not open_at:
            return
        wait = (open_at - datetime.now(CN_TZ)).total_seconds()
        if wait > args.arm:
            prev_open = rec.get("open_at")
            rec.update({"title": title, "open_at": open_at.strftime("%Y-%m-%d %H:%M:%S")})
            state["lectures"][data_id] = rec
            if prev_open != rec["open_at"]:
                log.info("登记卡点：《%s》%s 报名开放 %s", title, data_id, rec["open_at"])
            save_state(state)
            return
        if wait < -args.patience:
            return
        log.info(
            "进入卡点：《%s》%s（报名开放 %s，%+.0fs）",
            title, data_id, open_at.strftime("%Y-%m-%d %H:%M:%S"), wait,
        )
        target_ts = open_at.timestamp() - args.lead
    else:
        return

    result, detail = grab(api, data_id, args, target_ts=target_ts)

    entry = state["lectures"].setdefault(data_id, {"title": title})
    entry["title"] = title
    entry["detail"] = detail[:300]
    entry["at"] = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    entry["last_try"] = time.time()

    if result in ("registered",):
        entry["result"] = "registered"
        entry.pop("last_try", None)
        entry["verify_at"] = time.time() + args.verify_after
        today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
        counters = state.setdefault("counters", {})
        counters[today] = counters.get(today, 0) + 1
        log.info("√ 报名成功：《%s》（%s）", title, detail)
    elif result == "out_of_scope":
        entry["result"] = "out_of_scope"
        entry.pop("last_try", None)
        log.info("跳过《%s》：不在报名范围（%s）", title, detail)
    elif result == "ended":
        entry["result"] = "ended"
        entry.pop("last_try", None)
        log.info("跳过《%s》：报名已结束", title)
    elif result == "dry_run":
        entry["result"] = "dry_run"
        log.info("（dry-run）《%s》：%s", title, detail)
    elif result == "full":
        entry["result"] = "full"
        # 不要把 last_try 留在这里：讲座重新出现在「有余位」里就意味着又有名额，
        # 必须能立刻再抢，不能被 5 分钟重试间隔挡住。
        entry.pop("last_try", None)
        log.info("《%s》已满，等下一次放出", title)
    else:
        entry["result"] = result
        log.info("《%s》本次未成功：%s（%s）", title, result, detail)

    save_state(state)


def cookie_db_signature() -> float:
    """微信 cookie 库的最后修改时间，用来判断"用户是否在微信里重新登录过"。"""
    base = Path(os.environ.get("APPDATA", "")) / "Tencent/xwechat/radium/web/profiles"
    latest = 0.0
    try:
        for path in base.glob("*/Network/Cookies"):
            latest = max(latest, path.stat().st_mtime)
    except OSError:
        pass
    return latest


def verify_registrations(api: TjLecture, state: dict) -> None:
    """报名成功后隔一段时间复核，抓"当时成功、后来被回滚"的假成功。"""
    now = time.time()
    changed = False
    for data_id, rec in list(state["lectures"].items()):
        if rec.get("result") != "registered" or not rec.get("verify_at"):
            continue
        if now < rec["verify_at"]:
            continue
        rec.pop("verify_at", None)
        try:
            result = api.signup_result(data_id)
        except TokenExpired:
            raise
        except (ApiError, OSError) as exc:
            log.warning("复核《%s》失败，稍后再试：%s", rec.get("title"), exc)
            rec["verify_at"] = time.time() + 600
            changed = True
            continue
        if result.get("state") == 1:
            log.info("复核通过：《%s》仍有效（报名时间 %s）", rec.get("title"), result.get("signUpTime"))
        else:
            # 可能是你手动取消的；只记录，绝不重新抢回来
            log.warning(
                "《%s》已不在报名状态（state=%s），记为已取消，不再重抢",
                rec.get("title"), result.get("state"),
            )
            rec["result"] = "cancelled"
            rec["detail"] = f"复核 state={result.get('state')}"
            rec.pop("last_try", None)
            today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
            counters = state.setdefault("counters", {})
            if counters.get(today, 0) > 0:
                counters[today] -= 1
        changed = True
    if changed:
        save_state(state)


def refresh_cookie() -> bool:
    script = ROOT / "refresh-cookie.ps1"
    if not script.exists():
        log.error("找不到 refresh-cookie.ps1，无法自动续期")
        return False
    log.warning("凭证失效，尝试从微信本地库自动续期 ...")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.error("续期脚本执行失败：%s", exc)
        return False
    if proc.returncode == 0:
        log.info("√ 续期成功")
        return True
    log.error("续期失败（退出码 %s）：%s", proc.returncode, (proc.stdout or "")[-500:])
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="同济高等讲堂常驻自动报名")
    parser.add_argument("--poll", type=float, default=1.0, help="健康时的轮询间隔（快档）")
    parser.add_argument("--poll-slow", type=float, default=5.0, help="被限流后的轮询间隔（慢档）")
    parser.add_argument("--probe-after", type=float, default=1800.0, help="慢档持续多少秒后试探提速")
    parser.add_argument("--slow-poll", type=float, default=600.0, help="拉「未开始」列表间隔")
    parser.add_argument("--level", type=int, default=2, help="只抢某级别：0 全部 / 1 校级 / 2 院级（默认只抢院级）")
    parser.add_argument("--arm", type=float, default=180.0, help="开放前多少秒进入卡点")
    parser.add_argument("--lead", type=float, default=0.4)
    parser.add_argument("--patience", type=float, default=180.0, help="卡点后最多坚持秒数")
    parser.add_argument("--now-patience", type=float, default=20.0, help="已开放讲座单次尝试的坚持秒数")
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--retry-gap", type=float, default=300.0, help="同一讲座两次尝试的最小间隔")
    parser.add_argument("--max-per-day", type=int, default=0, help="每天最多报名场次，0 不限")
    parser.add_argument("--heartbeat", type=float, default=600.0, help="心跳日志间隔秒数")
    parser.add_argument("--verify-after", type=float, default=600.0, help="报名成功后多少秒复核一次")
    parser.add_argument("--session-ttl", type=float, default=1800.0, help="多少秒重建一次连接，0 不重建")
    parser.add_argument("--ua", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true", help="只跑一轮")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging()
    _lock = acquire_single_instance()
    state = load_state()
    refresh_skips()
    api: TjLecture | None = None
    next_slow = 0.0
    last_beat = time.time()
    polls = 0
    fail_streak = 0
    last_refresh = 0.0
    db_sig = 0.0
    refresh_fails = 0
    api_born = 0.0
    # 自适应：健康时快档，被限流自动降慢档，隔一段时间再试探提速
    fast_mode = True
    degraded_until = 0.0
    probe_wait = args.probe_after
    fast_since = 0.0

    log.info(
        "守护启动：poll=%.0fs(慢档%.0fs) slow-poll=%.0fs arm=%.0fs dry-run=%s",
        args.poll, args.poll_slow, args.slow_poll, args.arm, args.dry_run,
    )

    while True:
        cycle_start = time.time()
        try:
            refresh_skips()
            if api is None:
                api = make_api(args)
                api.sync_time()
                api_born = time.time()
            elif args.session_ttl and time.time() - api_born > args.session_ttl:
                # 定期换新连接，避免长期复用被服务端掐断的 socket
                api = make_api(args)
                api.sync_time()
                api_born = time.time()

            # 有余位：能报就报，顺带捡漏（院级已满的讲座一旦有人退就在这里冒出来）
            for row in fetch_all(api, status=1, time_filter=0, class_level=args.level):
                handle_row(api, row, args, state)

            # 未开始：登记卡点（同样只登记目标级别）
            if time.time() >= next_slow:
                for row in fetch_all(api, status=3, time_filter=0, class_level=args.level):
                    handle_row(api, row, args, state)
                next_slow = time.time() + args.slow_poll

            # 复核已报名的讲座，抓"当时成功、后来回滚"的假成功
            verify_registrations(api, state)

            fail_streak = 0
            if not fast_mode and time.time() >= degraded_until:
                fast_mode = True
                fast_since = time.time()
                log.info("慢档已跑满 %.0f 分钟，试探恢复快档 %.0fs", probe_wait / 60, args.poll)

            if args.once:
                log.info("单轮结束")
                return 0

            polls += 1
            if time.time() - last_beat >= args.heartbeat:
                today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
                log.info(
                    "心跳：轮询 %d 次，今日已报 %d 场，跟踪 %d 场",
                    polls, state.get("counters", {}).get(today, 0), len(state["lectures"]),
                )
                last_beat = time.time()

        except (TokenExpired, ApiError, OSError) as exc:
            text = str(exc)
            if isinstance(exc, TokenExpired) or is_auth_error(text):
                api = None
                sig = cookie_db_signature()
                db_changed = (not db_sig) or abs(sig - db_sig) >= 1
                wait_s = min(300 * (2 ** min(refresh_fails, 3)), 2400)
                if not db_changed:
                    # 微信库没动说明你还没重新登录，安静等着，不刷屏
                    log.info(
                        "登录态失效，等你用电脑微信打开一次讲座页（%d 分钟后再检查）",
                        wait_s // 60,
                    )
                    time.sleep(wait_s)
                    continue
                db_sig = sig
                last_refresh = time.time()
                if refresh_cookie():
                    refresh_fails = 0
                    fail_streak = 0
                    log.info("续期成功，恢复轮询")
                else:
                    refresh_fails += 1
                    log.error(
                        "续期失败（连续 %d 次）：用电脑微信打开 "
                        "https://lecture.tongji.edu.cn/wxpage/index 一次，让它自动重新登录；"
                        "%d 分钟后自动再试",
                        refresh_fails, wait_s // 60,
                    )
                    time.sleep(wait_s)
                continue

            fail_streak += 1
            if fail_streak >= 3 and fast_mode:
                fast_mode = False
                degraded_until = time.time() + probe_wait
                log.warning(
                    "连续失败，判定被限流：降到慢档 %.0fs，%.0f 分钟后再试探快档",
                    args.poll_slow, probe_wait / 60,
                )
                if fast_since and time.time() - fast_since < probe_wait:
                    probe_wait = min(probe_wait * 2, 14400)
                    log.info("提速不久又被限流，下次试探间隔延长到 %.0f 分钟", probe_wait / 60)
            elif not fast_mode:
                # 慢档里又失败，说明封禁还没过，把试探时间往后推
                degraded_until = time.time() + probe_wait
            # 连续连接失败多半是被限流，退避逐步拉长到 10 分钟，让封禁过期
            delay = min(max(args.poll, 1.0) * (2 ** min(fail_streak, 8)), 600.0)
            hint = "（疑似被限流，先冷静一会儿）" if fail_streak >= 5 else ""
            log.warning(
                "循环出错（连续 %d 次）%s：%s，%.0fs 后重试",
                fail_streak, hint, text[:150], delay,
            )
            # 连接被重置时，连接池里可能全是坏 socket；丢弃 session 下一轮重连
            api = None
            time.sleep(delay + random.uniform(0, 5))
            continue

        interval = args.poll if fast_mode else args.poll_slow
        elapsed = time.time() - cycle_start
        time.sleep(max(0.2, interval - elapsed) + random.uniform(0, min(0.3, interval * 0.2)))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log.info("收到中断，退出")
        raise SystemExit(0)
