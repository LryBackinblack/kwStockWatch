#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 mitmproxy 抓包 dump 里提取最新的 x-wx-token，验证后写入 token.txt

    python refresh_token.py            # 提取并写入
    python refresh_token.py --check    # 只看结果，不写入
    python refresh_token.py --watch    # 常驻，发现新抓包就自动续 token

前提：mitmproxy 抓包环境在跑，且你重新打开过小程序（让它带上新 token 发请求）。
"""

import argparse
import pathlib
import re
import time
from datetime import datetime

import watch_stock as ws

DUMPS = pathlib.Path(r"C:\Users\Linre\.mitmproxy\dumps")
TOKEN_RE = re.compile(r"^x-wx-token:\s*(\S+)\s*$", re.I | re.M)
MAX_CANDIDATES = 5


def collect_candidates():
    """扫描 dump，返回按抓取时间从新到旧的 [(token, mtime)]，token 去重。"""
    if not DUMPS.is_dir():
        return []
    newest = {}
    for f in DUMPS.glob("*.req.txt"):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = TOKEN_RE.search(text)
        if not m:
            continue
        token, mtime = m.group(1), f.stat().st_mtime
        if token not in newest or mtime > newest[token]:
            newest[token] = mtime
    return sorted(newest.items(), key=lambda kv: kv[1], reverse=True)


def verify(token):
    """返回 (可用?, 说明)。直接看 errcode，不依赖能否搜到目标商品。"""
    try:
        result = ws.call_api(token)
    except Exception as e:
        return None, f"网络错误 {type(e).__name__}: {e}"
    code = str(result.get("errcode"))
    if code == "0":
        return True, "验证通过"
    if code == "1041":
        return False, f"已失效（{result.get('errmsg')}）"
    return False, f"异常 errcode={code} {result.get('errmsg')}"


def current_token():
    if ws.TOKEN_FILE.exists():
        return ws.TOKEN_FILE.read_text(encoding="utf-8").strip()
    return ""


def refresh(write=True):
    candidates = collect_candidates()
    if not candidates:
        print(f"{DUMPS} 里没有带 x-wx-token 的请求。")
        print("请先确认抓包在运行，并重新打开一次小程序。")
        return None

    cur = current_token()
    print(f"抓到 {len(candidates)} 个不同的 token，从新到旧逐个验证：")

    for token, mtime in candidates[:MAX_CANDIDATES]:
        when = datetime.fromtimestamp(mtime)
        ok, msg = verify(token)
        tag = "新" if token != cur else "当前"
        print(f"  [{when:%m-%d %H:%M:%S}] {token[:12]}… ({tag})  {msg}")

        if not ok:
            continue

        if token == cur:
            print("当前 token 仍然有效，无需更新。")
            return token

        if write:
            ws.TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
            print(f"已更新 {ws.TOKEN_FILE}（来源 {when:%m-%d %H:%M:%S}）")
        else:
            print("（--check 模式，未写入）")
        return token

    print("没有验证通过的 token —— 说明抓到的都过期了。")
    print("请重新打开小程序触发一次请求，再跑一遍。")
    return None


def watch(interval):
    print(f"常驻监听 {DUMPS}（每 {interval}s 检查一次），Ctrl-C 退出")
    seen = -1.0
    while True:
        try:
            newest = max(
                (f.stat().st_mtime for f in DUMPS.glob("*.req.txt")), default=0.0
            )
            if newest > seen:
                seen = newest
                refresh()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"检查出错：{type(e).__name__}: {e}")
        time.sleep(interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只验证，不写入")
    ap.add_argument("--watch", action="store_true", help="常驻监听新抓包")
    ap.add_argument("--watch-interval", type=int, default=10, help="监听间隔秒数")
    args = ap.parse_args()

    if args.watch:
        watch(args.watch_interval)
    else:
        refresh(write=not args.check)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止")
