#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
科技主线 2x/3x ETF 决策辅助引擎
================================
为 Daniel 的期权交易服务，两个模式：

  premarket (21:00 北京)  → 盘前决策底稿：昨收 + 盘前方向 + if-then 今晚怎么打
  open30    (22:05 北京)  → 开盘半小时信号：开盘30分钟方向+量能，判断 V 反是否触发

核心原则（Daniel 真金白银，不容有坑）：
  1. 只给"方向 + 强弱 + if-then 规则"，不报精确到应该用哪个价位落单
     —— 精确下单用手机券商 App 实时价，数据延时不影响方向判断
  2. 信号用"方向 + 相对量能"，不用"绝对价"，对 15 分钟延时天然不敏感
  3. 所有判断标注数据时点（昨收 / 盘前 / 开盘30分钟）
  4. 数据交叉验证：新浪 + 腾讯双源，对不上标 ⚠️

数据源：
  - 昨日收盘：新浪日K (us_stock_kline_sina)，稳定可靠
  - 盘前/实时：新浪 gb_XXXX（盘前时段字段[1]自动切盘前价），腾讯 usXXXX 交叉验证

用法：
  python tech-etf-signal.py premarket
  python tech-etf-signal.py open30

输出：print Markdown（供 workflow 抓取推送到 Bark/飞书）
"""

import requests, re, json, sys
from datetime import datetime, timezone, timedelta

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# 科技主线 9 只标的：{ticker: (赛道, 杠杆, 优先级)}
TICKERS = {
    "SOXL": ("AI芯片", "3x", 1),
    "MUU":  ("存储·美光", "2x", 2),
    "NVDL": ("AI芯片·NVDA", "2x", 2),
    "TQQQ": ("科技宽基", "3x", 3),
    "RAM":  ("DRAM", "2x", 3),
    "DRAM": ("存储行业", "1x", 3),
    "SNXX": ("存储·闪迪", "2x", 4),
    "COHX": ("光模块·相干", "2x", 4),
    "AAOX": ("光模块·AAOI", "2x", 4),
}

# V 反信号阈值（对应 v14 面板 & 末日期权文件的"放量 V 反"窗口）
REVERSAL_PCT = 8.0      # 单日涨幅门槛 %
VOL_SPIKE_MULT = 2.0    # 量能倍数 vs 60日均量
PRE_JUMP_PCT = 3.0      # 盘前跳空预警阈值 %


def beijing_now():
    return datetime.now(timezone(timedelta(hours=8)))


def is_us_trading_day(now=None):
    """美股交易日判断：周一~周五（北京时区）。周末/假日返回 False。
    注意：这里只挡周末，美股节假日（如圣诞、感恩节）需在规则里留白。"""
    if now is None:
        now = beijing_now()
    return now.weekday() < 5  # 0=周一 ... 4=周五；5/6=周末


def within_premarket(now=None):
    """是否在美股盘前时段（北京 16:00~21:30，夏令时）。粗判：用于标注数据含义。"""
    if now is None:
        now = beijing_now()
    minutes = now.hour * 60 + now.minute
    return 16 * 60 <= minutes < 21 * 60 + 30


def us_stock_kline_sina(ticker, num=120):
    """新浪美股日K（收盘价），返回时间正序列表"""
    url = "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var/US_MinKService.getDailyK"
    params = {"symbol": ticker.upper(), "num": num}
    try:
        r = requests.get(url, params=params,
                         headers={"Referer": "https://finance.sina.com.cn/"}, timeout=15)
        m = re.search(r'\((\[.+\])\)', r.text)
        if not m:
            return []
        items = json.loads(m.group(1))
        out = []
        for it in items:
            out.append({
                "date": it.get("d"),
                "open": float(it.get("o", 0)),
                "high": float(it.get("h", 0)),
                "low": float(it.get("l", 0)),
                "close": float(it.get("c", 0)),
                "volume": int(it.get("v", 0)),
            })
        return out
    except Exception:
        return []


def us_quote_sina(ticker):
    """新浪美股实时/盘前行情，返回 dict 或 None"""
    url = f"https://hq.sinajs.cn/list=gb_{ticker.lower()}"
    try:
        r = requests.get(url, headers={"Referer": "https://finance.sina.com.cn/",
                                       "User-Agent": UA}, timeout=10)
        r.encoding = "gbk"
        m = re.search(r'"(.+)"', r.text)
        if not m:
            return None
        f = m.group(1).split(",")
        if len(f) < 27:
            return None
        return {
            "name": f[0],
            "price": float(f[1]) if f[1] else None,
            "chg_pct": float(f[2]) if f[2] else None,
            "prev_close": float(f[26]) if f[26] else None,
            "open": float(f[5]) if len(f) > 5 and f[5] else None,
            "high": float(f[6]) if len(f) > 6 and f[6] else None,
            "low": float(f[7]) if len(f) > 7 and f[7] else None,
            "volume": float(f[10]) if len(f) > 10 and f[10] else None,
        }
    except Exception:
        return None


def us_quote_tencent(ticker):
    """腾讯美股行情（交叉验证用）"""
    url = f"https://qt.gtimg.cn/q=us{ticker.upper()}"
    try:
        r = requests.get(url, timeout=10)
        r.encoding = "gbk"
        m = re.search(r'"(.+)"', r.text)
        if not m:
            return None
        f = m.group(1).split("~")
        if len(f) < 40:
            return None
        return {
            "price": float(f[3]) if f[3] else None,
            "chg_pct": float(f[32]) if f[32] else None,
        }
    except Exception:
        return None


def data_phase_note():
    """标注当前数据属于哪个阶段，避免把昨收当实时/盘前价误导 Daniel。"""
    now = beijing_now()
    if not is_us_trading_day(now):
        return "🛑 美股休市（周末/假日），以下为最近交易日收盘数据，非实时"
    minutes = now.hour * 60 + now.minute
    if minutes < 16 * 60:
        return "🕓 盘前未开始（<16:00），数据=昨收"
    elif minutes < 21 * 60 + 30:
        return "🌅 盘前时段（16:00-21:30），价格=盘前实时（量小易变，仅方向参考）"
    else:
        return "🟢 盘中时段（>21:30），价格=盘中实时（延时约15分钟）"


def calc_v_signal(ticker, klines):
    """基于日K判断昨日的放量 V 反状态（供 premarket 模式用）"""
    if len(klines) < 40:
        return None
    closes = [k["close"] for k in klines]
    vols = [k["volume"] for k in klines]
    last = klines[-1]
    prev = klines[-2]
    prevprev = klines[-3]

    chg_pct = (last["close"] - prev["close"]) / prev["close"] * 100 if prev["close"] else 0
    avg_vol_60 = sum(vols[-61:-1]) / 60 if len(vols) >= 62 and sum(vols[-61:-1]) else 1
    vol_ratio = last["volume"] / avg_vol_60 if avg_vol_60 else 0
    prev_down = prev["close"] < prevprev["close"]
    v_reversal = chg_pct >= REVERSAL_PCT and vol_ratio >= VOL_SPIKE_MULT and prev_down

    # 短期趋势：最近5日 vs 更早5日
    if len(closes) >= 10:
        chg5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if closes[-6] else 0
    else:
        chg5 = 0

    return {
        "ticker": ticker,
        "date": last["date"],
        "close": closes[-1],
        "chg_pct": round(chg_pct, 2),
        "vol_ratio": round(vol_ratio, 2),
        "v_reversal": v_reversal,
        "chg5": round(chg5, 2),
    }


def build_premarket_report():
    """21:00 盘前决策底稿"""
    now = beijing_now()
    lines = []
    lines.append(f"🌙 盘前决策底稿 · {now.strftime('%m-%d %H:%M')} 北京")
    lines.append(f"> {data_phase_note()}")
    lines.append("")

    rows = []
    anomalies = []
    for t in TICKERS:
        k = us_stock_kline_sina(t, 120)
        q = us_quote_sina(t)
        sector, lev, pri = TICKERS[t]
        if not k:
            continue
        last_close = k[-1]["close"]
        sig = calc_v_signal(t, k)

        # 盘前价
        pre_q = q
        pre_price = pre_q["price"] if pre_q and pre_q["price"] else None
        pre_chg = None
        if pre_price and last_close:
            pre_chg = (pre_price - last_close) / last_close * 100

        # 交叉验证（盘前/实时）
        cross_note = ""
        if pre_q and pre_price:
            tq = us_quote_tencent(t)
            if tq and tq["price"]:
                diff = abs(pre_price - tq["price"]) / pre_price * 100
                if diff > 2:
                    cross_note = f" ⚠️双源差{diff:.0f}%"
        rows.append({
            "ticker": t, "sector": sector, "lev": lev, "pri": pri,
            "last_close": last_close,
            "pre_price": pre_price, "pre_chg": pre_chg,
            "chg5": sig["chg5"] if sig else 0,
            "v_reversal": sig["v_reversal"] if sig else False,
            "cross_note": cross_note,
        })
        if pre_chg is not None and abs(pre_chg) >= PRE_JUMP_PCT:
            anomalies.append((t, sector, pre_chg))

    rows.sort(key=lambda x: x["pri"])

    # 表
    lines.append("| 标的 | 赛道 | 昨收 | 盘前 | 盘前涨跌 | 5日趋势 | 状态 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        pre_str = f"{r['pre_price']:.2f}" if r["pre_price"] else "—"
        prechg_str = f"{r['pre_chg']:+.2f}%" if r["pre_chg"] is not None else "—"
        status = "🔥昨V反" if r["v_reversal"] else "—"
        lines.append(f"| {r['ticker']} | {r['sector']} | {r['last_close']:.2f} | {pre_str} | {prechg_str}{r['cross_note']} | {r['chg5']:+.1f}% | {status} |")

    lines.append("")
    lines.append("## 今晚 if-then（开盘 30 分钟内执行）")
    lines.append("")

    if anomalies:
        lines.append("### ⚡ 盘前异动（跳空 ≥3%）")
        for t, sector, chg in anomalies:
            direction = "高开" if chg > 0 else "低开"
            lines.append(f"- {t}({sector}) 盘前{direction} {chg:+.1f}%")
        lines.append("")
    else:
        lines.append("### 盘前无异动（无标的跳空 ≥3%）")
        lines.append("")

    lines.append("### 买入规则（严格按 v14，不追高不接刀）")
    lines.append("```")
    lines.append("开盘 30 分钟（21:30→22:00）观察，10:00 前后才决策：")
    lines.append("IF  某标的涨 ≥ +8% 且 量 ≥ 2x 60日均量 且 昨日下跌（真 V 反）")
    lines.append("    → 买该标的 CALL（短 DTE OTM），仓位 ≤15%，当天/次日了结")
    lines.append("ELSEIF  某标的跌 ≥ -5% 且 放量（破位下杀）")
    lines.append("    → 不动。下跌中继不接飞刀，宁可错过")
    lines.append("ELSE")
    lines.append("    → 不动。$377 的优势是「等得起」")
    lines.append("```")
    lines.append("")
    lines.append(f"⚠️ 数据时点：昨收=上周五收盘，盘前=新浪实时盘前价（量小易变，仅方向参考）。精确下单用手机 App 实时价。")
    return "\n".join(lines)


def build_open30_report():
    """22:05 开盘半小时信号"""
    now = beijing_now()
    lines = []
    lines.append(f"⚡ 开盘半小时信号 · {now.strftime('%m-%d %H:%M')} 北京")
    lines.append(f"> {data_phase_note()}")
    lines.append("")

    rows = []
    triggered = []
    for t in TICKERS:
        k = us_stock_kline_sina(t, 120)
        q = us_quote_sina(t)
        sector, lev, pri = TICKERS[t]
        if not k or not q:
            continue
        last_close = k[-1]["close"]
        pre_open = q["open"]
        price = q["price"]
        chg = q["chg_pct"]  # 盘中相对昨收涨跌
        chg_from_open = None
        if pre_open and price and pre_open:
            chg_from_open = (price - pre_open) / pre_open * 100

        # 量能（实时量 vs 60日均量，开盘半小时量是全天约1/13，这里用成交量比值粗判）
        sig = calc_v_signal(t, k)
        avg_vol_daily = sum(kk["volume"] for kk in k[-61:-1]) / 60 if len(k) >= 62 else 0
        vol_now = q["volume"] if q["volume"] else 0

        rows.append({
            "ticker": t, "sector": sector, "lev": lev, "pri": pri,
            "last_close": last_close, "price": price, "chg": chg,
            "chg_from_open": chg_from_open, "vol_now": vol_now,
            "prev_down": sig and (k[-2]["close"] < k[-3]["close"]),
        })
        # 开盘半小时触发判断：涨幅>5% 且 从开盘价继续上攻
        if chg is not None and chg >= 5.0 and chg_from_open is not None and chg_from_open > 0:
            triggered.append((t, sector, lev, chg, chg_from_open))

    rows.sort(key=lambda x: x["pri"])

    lines.append("| 标的 | 赛道 | 昨日收盘 | 现价 | 涨跌% | 开盘后 | 状态 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        price_str = f"{r['price']:.2f}" if r["price"] else "—"
        chg_str = f"{r['chg']:+.2f}%" if r["chg"] is not None else "—"
        coa = f"{r['chg_from_open']:+.1f}%" if r["chg_from_open"] is not None else "—"
        status = "🟢上攻" if r["chg_from_open"] is not None and r["chg_from_open"] > 0 else ("🔴破位" if r["chg_from_open"] is not None and r["chg_from_open"] < -1 else "—")
        lines.append(f"| {r['ticker']} | {r['sector']} | {r['last_close']:.2f} | {price_str} | {chg_str} | {coa} | {status} |")

    lines.append("")
    if triggered:
        lines.append("## 🚨 开盘半小时上攻（涨幅≥5%且开盘后继续走高）")
        for t, sector, lev, chg, coa in triggered:
            lines.append(f"- 🔥 {t}({sector} {lev}) 涨 {chg:+.1f}%，开盘后 {coa:+.1f}% → 关注，但不等于可买")
        lines.append("")
        lines.append("> 注意：开盘半小时量未放足，需等 22:30 后量能确认。涨幅≥8%+量≥2x 才是真 V 反。")
    else:
        lines.append("## 开盘半小时：无标的触发上攻信号")
        lines.append("")
        lines.append("> 继续等。不追高、不接刀。真正的 V 反信号是「涨≥8% + 量≥2x + 昨日下跌」，半小时内通常走不完。")
    lines.append("")
    lines.append("⚠️ 数据延时约 15 分钟，方向/涨跌可靠，精确下单用手机 App 实时价。")
    return "\n".join(lines)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "premarket"
    if mode == "open30":
        print(build_open30_report())
    else:
        print(build_premarket_report())
