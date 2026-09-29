#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单次库存检查（给 GitHub Actions 定时跑）：查一次，状态变化时推送到飞书。

    FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx python ci_check.py

本地也能直接跑。token 来自 token.txt（CI 里由 WX_TOKEN secret 写入），
云端无法自动续期 —— 失效时会推送一次提醒，本地跑 refresh_token.py
拿到新 token 后更新 secret 即可。

与 watch_stock.py 的区别：进程用完即退，所以状态存在 .stock_state.json，
由 Actions cache 在两次运行之间传递，避免有货期间每轮都重复推送。

退出码：0 正常（无论有货与否，包括已处理的失败）/ 1 未预期错误
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

import watch_stock as ws

STATE_FILE = ws.BASE / ".stock_state.json"
WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()
SECRET = os.environ.get("FEISHU_SECRET", "").strip()


def load_state():
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )


def push_feishu(text):
    if not WEBHOOK:
        ws.log("未配置 FEISHU_WEBHOOK，跳过推送")
        return

    body = {"msg_type": "text", "content": {"text": text}}
    if SECRET:  # 机器人开了「签名校验」才需要
        ts = str(int(time.time()))
        body["timestamp"] = ts
        body["sign"] = base64.b64encode(
            hmac.new(
                f"{ts}\n{SECRET}".encode("utf-8"), digestmod=hashlib.sha256
            ).digest()
        ).decode("utf-8")

    req = urllib.request.Request(
        WEBHOOK,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ws.log(f"飞书推送 HTTP {resp.status} {resp.read().decode('utf-8')}")
    except (urllib.error.URLError, OSError) as e:
        ws.log(f"飞书推送失败：{e}")


def read_token():
    if not ws.TOKEN_FILE.exists():
        return ""
    return ws.TOKEN_FILE.read_text(encoding="utf-8").strip()


def main():
    state = load_state()

    token = read_token()
    if not token:
        # secret 还没配好时不要报错退出，否则每 5 分钟给仓库管理员发一封失败邮件
        ws.log("token.txt 为空 —— 请先配置 WX_TOKEN secret")
        save_state(state)
        return 0

    try:
        snap = ws.probe(token)
    except (ws.TokenExpired, urllib.error.URLError, TimeoutError, RuntimeError) as e:
        ws.log(f"检查失败：{e}")
        err = str(e)
        if state.get("error") != err:
            push_feishu(
                f"⚠️ 库存监控异常\n{err}\n\n"
                "若为 token 失效：本地跑 refresh_token.py 后更新 WX_TOKEN secret"
            )
            state["error"] = err
            save_state(state)
        return 0

    flag = "有货" if snap["buyable"] else "缺货"
    ws.log(f"{flag}  库存={snap['stock']}  售价={snap['price']}  销量={snap['sales']}")

    if snap["buyable"] and not state.get("buyable"):
        push_feishu(
            f"🛒 补货了！{snap['title']}\n"
            f"库存 {snap['stock']} 件　售价 {snap['price']} 元"
        )

    save_state(
        {
            "buyable": snap["buyable"],
            "error": None,
            "checkedAt": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
