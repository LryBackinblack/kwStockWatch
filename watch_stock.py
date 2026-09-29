#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""凯威机车商城 —— 指定商品库存监控

    python watch_stock.py              # 每 5~10 分钟随机轮询一次
    python watch_stock.py --min 120 --max 240
    python watch_stock.py -i 30        # 固定 30 秒（调试用）
    python watch_stock.py --once       # 只查一次

token 过期（errcode 1041）时改 token.txt 即可，无需重启脚本。
"""

import argparse
import gzip
import json
import pathlib
import random
import sys
import time
import urllib.error
import urllib.request
import winsound
from datetime import datetime, timedelta

BASE = pathlib.Path(__file__).resolve().parent
TOKEN_FILE = BASE / "token.txt"
LOG_FILE = BASE / "stock.log"

API = "https://xapi.weimob.com/api3/mall/navigation/goods/getClassifyAndGoodsList"
APPID = "wxae3970ef7d54457b"
CLASSIFY_ID = 14018496755245
TARGET_ID = 155319675755245
TARGET_TITLE = "时光1200 换档臂组件"
SEARCH_KEYWORD = "换档臂"

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

BASIC_INFO = {
    "vid": 6016350687245,
    "vidType": 2,
    "bosId": 4021863929245,
    "productId": 145,
    "productInstanceId": 12621644245,
    "productVersionId": "12010",
    "merchantId": 2000309988245,
    "tcode": "weimob",
    "cid": 676866245,
}


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_token():
    if not TOKEN_FILE.exists():
        sys.exit(f"缺少 {TOKEN_FILE}，请把 x-wx-token 的值写入该文件")
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        sys.exit("token.txt 为空")
    return token


def build_payload():
    return {
        "appid": APPID,
        "basicInfo": BASIC_INFO,
        "queryParameter": {
            "source": 1,
            "classifyId": CLASSIFY_ID,
            "pageNum": 1,
            "pageSize": 7,
            "goodsListRequest": {
                "orderBy": [{"field": "complex", "sort": "desc"}],
                "goodsClassifyId": 0,
                "goodsClassifyName": "全部商品",
                "search": SEARCH_KEYWORD,
                "searchType": 1,
                "sortByRule": 2,
                "sortBySearch": 1,
                "propValueList": [],
            },
        },
    }


def call_api(token):
    headers = {"content-type": "application/json", "x-wx-token": token}
    req = urllib.request.Request(
        API,
        data=json.dumps(build_payload()).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    # 显式直连：urllib 默认会读 Windows 系统代理，抓包开着时会被拽进 mitmproxy
    with _OPENER.open(req, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def find_target(payload_json):
    data = payload_json.get("data") or {}
    for classify in data.get("classifies") or []:
        for group in classify.get("secondClassifyList") or []:
            page = ((group.get("goods") or {}).get("paginationData") or {}).get(
                "pageList"
            ) or []
            for item in page:
                if item.get("id") == TARGET_ID:
                    return item
            for item in page:
                if item.get("title") == TARGET_TITLE:
                    return item
    return None


def probe(token):
    result = call_api(token)
    code = str(result.get("errcode"))
    if code == "1041":
        raise TokenExpired(result.get("errmsg"))
    if code != "0":
        raise RuntimeError(f"接口报错 errcode={code} errmsg={result.get('errmsg')}")
    item = find_target(result)
    if item is None:
        raise RuntimeError(f"没搜到目标商品（search={SEARCH_KEYWORD!r}）")
    return {
        "stock": item.get("availableStockNum") or 0,
        "buyable": bool(item.get("showAddCart")) and (item.get("availableStockNum") or 0) > 0,
        "price": item.get("minSalePrice"),
        "sales": item.get("goodsSaleNum"),
        "title": item.get("title"),
    }


class TokenExpired(Exception):
    pass


def next_delay(args):
    if args.interval:
        return float(args.interval)
    lo, hi = min(args.min_interval, args.max_interval), max(
        args.min_interval, args.max_interval
    )
    return random.uniform(lo, hi)


def sleep_until_next(args):
    delay = next_delay(args)
    nxt = datetime.now() + timedelta(seconds=delay)
    log(f"下次检查 {nxt:%H:%M:%S}（{delay / 60:.1f} 分钟后）")
    time.sleep(delay)


def alert(snapshot):
    print()
    print("=" * 56)
    print(f"  !! 有货了  {snapshot['title']}")
    print(f"  库存 {snapshot['stock']} 件    售价 {snapshot['price']} 元")
    print("=" * 56)
    print()
    for _ in range(3):
        winsound.Beep(1000, 250)
        time.sleep(0.12)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", dest="min_interval", type=int, default=300, help="最小间隔秒数")
    ap.add_argument("--max", dest="max_interval", type=int, default=600, help="最大间隔秒数")
    ap.add_argument("-i", "--interval", type=int, default=None, help="固定间隔秒数（覆盖 --min/--max）")
    ap.add_argument("--once", action="store_true", help="只查一次")
    args = ap.parse_args()

    if args.interval:
        span = f"固定 {args.interval}s"
    else:
        span = f"随机 {min(args.min_interval, args.max_interval)}~{max(args.min_interval, args.max_interval)}s"

    prev = None
    log(f"开始监控：{TARGET_TITLE}（间隔 {span}）")

    while True:
        try:
            snap = probe(load_token())
        except TokenExpired as e:
            log(f"!! token 已失效（{e}）。请更新 {TOKEN_FILE} 后脚本会自动继续")
            if args.once:
                return
            sleep_until_next(args)
            continue
        except (urllib.error.URLError, TimeoutError, RuntimeError) as e:
            log(f"请求失败：{e}")
            if args.once:
                return
            sleep_until_next(args)
            continue

        state = (snap["stock"], snap["buyable"])
        flag = "有货" if snap["buyable"] else "缺货"
        log(
            f"{flag}  库存={snap['stock']}  售价={snap['price']}  销量={snap['sales']}"
        )

        if snap["buyable"] and (prev is None or not prev[1]):
            alert(snap)
        prev = state

        if args.once:
            return
        sleep_until_next(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止")
