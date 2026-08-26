#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
科技主线 2x/3x ETF 决策辅助引擎
================================
为 Daniel 的期权交易服务，单一模式：

  premarket (21:00 北京)  → 盘前决策底稿：昨收 + 盘前方向 + if-then 今晚怎么打

  （open30 开盘半小时模式已于 2026-08-26 废弃：开盘初期 open 价不可靠
    + GitHub Actions cron 延迟 45-60 分钟，导致「开盘半小时」信号失真，
    拿盘前价冒充开盘价，对决策有害。已移除。）

核心原则（Daniel 真金白银，不容有坑）：
  1. 只给"方向 + 强弱 + if-then 规则"，不报精确到应该用哪个价位落单
     —— 精确下单用手机券商 App 实时价，数据延时不影响方向判断
  2. 信号用"方向 + 相对量能"，不用"绝对价"，对 15 分钟延时天然不敏感
  3. 所有判断标注数据时点（昨收 / 盘前）
  4. 数据交叉验证：新浪 + 腾讯双源，对不上标 ⚠️

数据源：
  - 昨日收盘：新浪日K (us_stock_kline_sina)，稳定可靠
  - 盘前/实时：新浪 gb_XXXX（盘前时段字段[21]），腾讯 usXXXX 交叉验证

用法：
  python tech-etf-signal.py

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
    """新浪美股实时/盘前行情，返回 dict 或 None。

    字段语义（实测 2026-08-24，经 Daniel 两次纠错后锁定）：
      [1] 最新价（盘前时段=昨收影子，不靠谱；盘中=实时价）
      [2] 涨跌%（相对它家的"昨收"，盘前时段是昨日涨跌，勿用）
      [21] 盘前/盘后最新价（盘前时段=真实盘前价）
      [22] 盘前涨跌%（分母用它家滞后的"昨收"字段[26]，勿信，要自己算）
      [24] 盘前时间戳（EDT）实时跳动 —— 判断数据新鲜度
      [25] 上次正式收盘时间戳 —— 锚定"是否是今天盘前"
      [26] 昨收（⚠️ 滞后一交易日，勿用作昨收，用日K最后一根）
    """
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

        premarket_price = float(f[21]) if len(f) > 21 and f[21] else None
        return {
            "name": f[0],
            "price": float(f[1]) if f[1] else None,
            "chg_pct": float(f[2]) if f[2] else None,
            "prev_close_sina": float(f[26]) if f[26] else None,
            "premarket_price": premarket_price,
            "premarket_chg_pct": float(f[22]) if len(f) > 22 and f[22] else None,
            "quote_time": f[3] if len(f) > 3 else None,
            "ext_time": f[24] if len(f) > 24 else None,       # 盘前时间戳，实时
            "last_close_time": f[25] if len(f) > 25 else None,  # 上次收盘时间戳
            "open": float(f[5]) if len(f) > 5 and f[5] else None,
            "high": float(f[6]) if len(f) > 6 and f[6] else None,
            "low": float(f[7]) if len(f) > 7 and f[7] else None,
            "volume": float(f[10]) if len(f) > 10 and f[10] else None,
        }
    except Exception:
        return None


def is_fresh_premarket(q):
    """判断字段[21]是否属于今天的盘前/盘后价。

    依据：字段[25]（上次正式收盘时间戳）。若它含今天的日期（美东月日），
    说明今天已收盘，字段[21]是盘后价；否则是今天的盘前价。
    返回 (是否可信, 说明文字)。
    """
    if not q or not q.get("last_close_time"):
        return False, "无时间戳"
    import datetime as _dt
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    now_edt = now_utc - _dt.timedelta(hours=4)  # 夏令时 EDT=UTC-4，粗判
    today_str = now_edt.strftime("%b %d")       # 如 "Aug 24"
    last_close_str = q["last_close_time"] or ""
    if today_str in last_close_str:
        # 上次收盘就是今天 → 已收盘，字段[21]是盘后价
        return False, "今日已收盘(盘后价)"
    # 上次收盘是过去某天 → 字段[21]是今天盘前价
    return True, f"盘前价(收盘锚定:{last_close_str})"


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
    """21:00 盘前决策底稿（手机友好纯文本，无 Markdown 表格线）"""
    now = beijing_now()
    lines = []
    lines.append(f"🌙 盘前决策 · {now.strftime('%m-%d %H:%M')}")
    lines.append(f"{data_phase_note()}")
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

        pre_q = q
        # 昨收一律用日K最后一根（死数据，正确）。绝不碰字段[26]（滞后一天）
        # 盘前价：字段[21]，但要经过新鲜度校验（用字段[25]收盘时间戳锚定）
        pre_price = None
        pre_chg = None
        pre_note = ""
        if pre_q:
            is_fresh, fresh_note = is_fresh_premarket(pre_q)
            if is_fresh and pre_q.get("premarket_price") is not None:
                pre_price = pre_q["premarket_price"]
                # 盘前涨跌%自己算，分母用日K昨收
                if last_close:
                    pre_chg = (pre_price - last_close) / last_close * 100
                pre_note = fresh_note
            else:
                # 字段[21]不可信（已收盘盘后价 / 无盘前数据），退回昨收并标注
                pre_price = last_close
                pre_chg = 0.0
                pre_note = "无盘前数据" if is_fresh else (fresh_note if fresh_note != "无时间戳" else "无盘前数据")

        # 交叉验证：盘前价多源比对（新浪[21] vs 腾讯）
        # 难点：腾讯盘前时段也返回昨收（死数据），只有它偏离昨收时才说明腾讯更新了盘前
        cross_note = ""
        if pre_price is not None and pre_price != last_close:
            tq = us_quote_tencent(t)
            tq_price = tq["price"] if tq and tq.get("price") else None
            if tq_price and last_close and abs(tq_price - last_close) / last_close > 0.5:
                # 腾讯价已偏离昨收 >0.5%，说明腾讯也在给盘前/盘中价，可比
                diff = abs(pre_price - tq_price) / pre_price * 100
                if diff > 2:
                    cross_note = " ⚠️双源差"

        rows.append({
            "ticker": t, "sector": sector, "lev": lev, "pri": pri,
            "last_close": last_close,
            "pre_price": pre_price, "pre_chg": pre_chg,
            "chg5": sig["chg5"] if sig else 0,
            "v_reversal": sig["v_reversal"] if sig else False,
            "cross_note": cross_note,
        })
        if pre_chg is not None and abs(pre_chg) >= PRE_JUMP_PCT:
            anomalies.append((t, sector, pre_chg, pre_price))

    rows.sort(key=lambda x: x["pri"])

    # 每标的一行：代号(赛道) 昨收→盘前 涨跌 [状态]
    for r in rows:
        pre_arrow = f"{r['last_close']:.2f}→{r['pre_price']:.2f}" if r["pre_price"] else f"{r['last_close']:.2f}→—"
        prechg = f"{r['pre_chg']:+.2f}%" if r["pre_chg"] is not None else "—"
        vflag = " 🔥V反昨" if r["v_reversal"] else ""
        trend5 = f"{r['chg5']:+.0f}%/5日"
        lines.append(f"{r['ticker']}({r['sector']}{r['lev']}) {pre_arrow} {prechg} {trend5}{vflag}{r['cross_note']}")

    lines.append("")
    lines.append("【今晚怎么打 v14】")
    if anomalies:
        for t, sector, chg, price in anomalies:
            direction = "高开" if chg > 0 else "低开"
            lines.append(f"⚡ {t}({sector}) 盘前{direction} {chg:+.1f}% ({price:.2f})")
    else:
        lines.append("盘前无跳空≥3%，正常开局")
    lines.append("开盘30分钟内只看不动，10点后：")
    lines.append("· 涨≥8%+量≥2x+昨日跌 → 买CALL(短DTE,≤15%)")
    lines.append("· 跌≥5%放量 → 不接飞刀")
    lines.append("· 其他 → 不动，等得起")
    lines.append("")
    lines.append("⚠️ 盘前价易变，落单用券商App实时价")
    return "\n".join(lines)


def build_open30_report():
    pass  # 已废弃：开盘半小时模式因开盘初期 open 价不可靠 + cron 延迟，数据失真，于 2026-08-26 移除


if __name__ == "__main__":
    # 只保留盘前决策模式。open30 已废弃。
    print(build_premarket_report())
