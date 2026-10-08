#!/usr/bin/env python3
"""價格突破策略回測(微台,日盤 08:45~13:45)。

用法:
    python3 breakout_backtest.py data.csv [--dt-col datetime] [--open-col open] ...
    python3 breakout_backtest.py --selftest

預設假設(尚未經使用者確認,見 ASSUMPTIONS):
 A1 成本 44 元 = 每次成交(進場或出場各一次),一個來回 88 元 (--cost-per round 可改)
 A2 R 用前一交易日(資料中的上一個日盤)的日盤高低;月結算日雖不交易,仍當作前一日
 A3 K 棒時間戳預設視為結束時間(--label),內部轉成開始時間;K 棒 O/H/L/C 內部走勢假設:
        收>=開: O -> L -> H -> C ;收<開: O -> H -> L -> C
 A4 開盤價 = 當日第一根日盤 K 棒的開盤價
 A5 進場價、停損價皆成交在線上;進場(含反手)那根 K 棒不檢查停損
 A6 反手單被停損也算一次停損;當天停損 2 次即停止,不再反手
 A7 13:25 以第一根 >=13:25 的 K 棒開盤價平倉;13:25 之後不進場
"""
import argparse
import sys
from datetime import date, time, timedelta

import pandas as pd

SESSION_START = time(8, 45)
SESSION_END = time(13, 45)   # K 棒開始時間 < 13:45 才算日盤
FLAT_TIME = time(13, 25)
MAX_STOPS = 2
POINT_VALUE = 10             # 微台 1 點 = 10 元


def is_settlement_day(d: date) -> bool:
    """每月第 3 個週三。"""
    return d.weekday() == 2 and 15 <= d.day <= 21


def bar_path(o, h, l, c):
    return [o, l, h, c] if c >= o else [o, h, l, c]


def run_day(bars, o_price, r):
    """bars: list of (time, o, h, l, c)。回傳 trades list of dict。"""
    red = o_price + r / 2
    green = o_price - r / 2
    yellow = o_price + 0.05 * r
    purple = o_price - 0.05 * r

    pos = 0            # +1 多, -1 空, 0 空手
    entry = None
    entry_time = None
    stop = None
    stops = 0
    trades = []

    def close(price, t, reason):
        nonlocal pos, entry, stop, entry_time
        pts = (price - entry) * pos
        trades.append(dict(entry_time=entry_time, exit_time=t, side=pos,
                           entry=entry, exit=price, points=pts, reason=reason))
        pos, entry, stop, entry_time = 0, None, None, None

    def open_pos(side, price, t, stop_price):
        nonlocal pos, entry, stop, entry_time
        pos, entry, stop, entry_time = side, price, stop_price, t

    for (t, o, h, l, c) in bars:
        if t >= FLAT_TIME:
            if pos != 0:
                close(o, t, "eod")
            break
        if stops >= MAX_STOPS:
            break

        path = bar_path(o, h, l, c)
        entered_this_bar = False
        for i in range(3):
            a, b = path[i], path[i + 1]
            lo, hi = min(a, b), max(a, b)
            cur = a
            # 同一段內可能連續觸發(進場後再碰線),迴圈處理
            for _ in range(4):
                cands = []   # (distance, kind, level)
                if pos == 0 and stops == 0:
                    if lo <= red <= hi and (b >= a or red != a):
                        cands.append((abs(red - cur), "enter_long", red))
                    if lo <= green <= hi:
                        cands.append((abs(green - cur), "enter_short", green))
                elif pos != 0 and not entered_this_bar:
                    if pos > 0 and lo <= stop <= hi:
                        cands.append((abs(stop - cur), "stop", stop))
                    if pos < 0 and lo <= stop <= hi:
                        cands.append((abs(stop - cur), "stop", stop))
                if not cands:
                    break
                # 只考慮仍在本段前進方向上的觸發(離目前位置最近者)
                cands = [x for x in cands
                         if (b >= cur and x[2] >= cur) or (b < cur and x[2] <= cur)]
                if not cands:
                    break
                _, kind, lvl = min(cands)
                if kind == "enter_long":
                    open_pos(+1, lvl, t, purple)
                    entered_this_bar = True
                elif kind == "enter_short":
                    open_pos(-1, lvl, t, yellow)
                    entered_this_bar = True
                else:  # stop
                    side = pos
                    close(lvl, t, "stop")
                    stops += 1
                    if stops < MAX_STOPS:
                        # 反手:多單停損->空,停損=紅線;空單停損->多,停損=綠線
                        if side > 0:
                            open_pos(-1, lvl, t, red)
                        else:
                            open_pos(+1, lvl, t, green)
                        entered_this_bar = True
                    else:
                        break
                cur = lvl
                lo, hi = (min(cur, b), max(cur, b))
        # end bar
    else:
        # 資料到 13:45 前都沒有 >=13:25 的 K 棒:以最後收盤平倉
        if pos != 0 and bars:
            close(bars[-1][4], bars[-1][0], "eod")
    if pos != 0:
        close(bars[-1][4], bars[-1][0], "eod")
    return trades


def _fmt_date(col):
    """支援 2024-01-02 / 2024/01/02 / 20240102。"""
    s = col.astype(str).str.strip()
    return s.str.replace(r"^(\d{4})(\d{2})(\d{2})$", r"\1-\2-\3", regex=True).str.replace("/", "-")


def _fmt_time(col):
    """支援 08:45 / 08:45:00 / 845 / 84500 / 084500。"""
    s = col.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    digits = s.str.fullmatch(r"\d+")
    z = s.where(~digits, s.str.zfill(6).where(s.str.len() > 4, s.str.zfill(4) + "00"))
    z = z.where(~digits, z.str[0:2] + ":" + z.str[2:4] + ":" + z.str[4:6])
    return z


def load(path, dt_col, o_col, h_col, l_col, c_col, label="end"):
    df = pd.read_csv(path)
    df.columns = [str(x).strip().lower() for x in df.columns]
    if dt_col.lower() in df.columns:
        ts = pd.to_datetime(df[dt_col.lower()])
    elif "date" in df.columns and "time" in df.columns:
        ts = pd.to_datetime(_fmt_date(df["date"]) + " " + _fmt_time(df["time"]))
    else:
        sys.exit(f"找不到時間欄位 {dt_col!r}(或 date+time);現有欄位:{list(df.columns)}")
    out = pd.DataFrame({
        "ts": ts,
        "o": df[o_col.lower()].astype(float),
        "h": df[h_col.lower()].astype(float),
        "l": df[l_col.lower()].astype(float),
        "c": df[c_col.lower()].astype(float),
    }).sort_values("ts")
    if label == "end":   # 時間戳是 K 棒結束時間(08:46 這根涵蓋 08:45~08:46)-> 轉成開始時間
        out["ts"] = out["ts"] - pd.Timedelta(minutes=1)
    out["date"] = out["ts"].dt.date
    out["time"] = out["ts"].dt.time
    out = out[(out["time"] >= SESSION_START) & (out["time"] < SESSION_END)]
    return out


def backtest(df, cost, cost_per="fill"):
    days = sorted(df["date"].unique())
    by_day = {d: g for d, g in df.groupby("date")}
    rows = []
    warn_open = 0
    for i, d in enumerate(days):
        if i == 0:
            continue  # 沒有前一日,無 R
        prev = by_day[days[i - 1]]
        r = prev["h"].max() - prev["l"].min()   # 只用前一日
        if is_settlement_day(d) or r <= 0:
            continue
        g = by_day[d]
        if g.iloc[0]["time"] != SESSION_START:
            warn_open += 1
        o_price = g.iloc[0]["o"]
        bars = list(zip(g["time"], g["o"], g["h"], g["l"], g["c"]))
        for tr in run_day(bars, o_price, r):
            tr["date"] = d
            tr["R"] = r
            fills = 2
            tr["cost"] = cost * fills if cost_per == "fill" else cost
            tr["pnl"] = tr["points"] * POINT_VALUE - tr["cost"]
            rows.append(tr)
    if warn_open:
        print(f"[警告] {warn_open} 天第一根 K 棒不是 08:45,開盤價以第一根為準", file=sys.stderr)
    return pd.DataFrame(rows)


def summarize(t):
    if t.empty:
        return "沒有交易"
    t = t.sort_values(["date", "entry_time"])
    eq = t["pnl"].cumsum()
    dd = (eq.cummax() - eq).max()
    wins = t[t["pnl"] > 0]["pnl"].sum()
    loss = -t[t["pnl"] <= 0]["pnl"].sum()
    return (f"交易數 {len(t)} | 交易日 {t['date'].nunique()} | 總損益 {t['pnl'].sum():,.0f} 元 | "
            f"勝率 {(t['pnl'] > 0).mean():.1%} | 獲利因子 {wins / loss if loss else float('inf'):.2f} | "
            f"最大回落 {dd:,.0f} 元 | 總成本 {t['cost'].sum():,.0f} 元")


def selftest():
    """用手算情境驗證狀態機。1 分 K,R=100,開盤 1000 => 紅1050 綠950 黃1005 紫995。"""
    O, R = 1000.0, 100.0
    T = lambda h, m: time(h, m)

    # 情境1:漲到紅線進多,收到 13:25 平倉 -> 多 @1050 平 @1060
    bars = [(T(8, 45), 1000, 1002, 998, 1001), (T(8, 46), 1001, 1055, 1000, 1052),
            (T(9, 0), 1052, 1070, 1050, 1060), (T(13, 25), 1060, 1061, 1059, 1060)]
    t = run_day(bars, O, R)
    assert len(t) == 1 and t[0]["side"] == 1 and t[0]["entry"] == 1050 and t[0]["exit"] == 1060, t

    # 情境2:進多後跌破紫線停損(995)並反手做空,反手單碰紅線(1050)再停損 -> 共 2 次後停止
    bars = [(T(8, 45), 1000, 1002, 998, 1001),
            (T(8, 46), 1001, 1052, 1000, 1051),   # 進多 1050,同根不檢查停損
            (T(8, 47), 1051, 1052, 990, 992),     # 跌破 995 停損,反手空 @995
            (T(8, 48), 992, 1051, 990, 1040),     # 空單碰 1050 停損 -> 第2次停損
            (T(8, 49), 1040, 900, 899, 900),      # 不應再交易
            (T(13, 25), 900, 900, 900, 900)]
    t = run_day(bars, O, R)
    assert [(x["side"], x["entry"], x["exit"]) for x in t] == [(1, 1050, 995), (-1, 995, 1050)], t

    # 情境3:先跌破綠線進空,碰黃線(1005)停損反手做多,反手停損=綠線(950)
    bars = [(T(8, 45), 1000, 1001, 949, 951),     # 進空 950,同根不檢查
            (T(8, 46), 951, 1006, 951, 1005),     # 碰 1005 停損,反手多 @1005
            (T(8, 47), 1005, 1005, 940, 945),     # 碰 950 停損
            (T(13, 25), 945, 945, 945, 945)]
    t = run_day(bars, O, R)
    assert [(x["side"], x["entry"], x["exit"]) for x in t] == [(-1, 950, 1005), (1, 1005, 950)], t

    # 情境4:13:25 之後不進場
    bars = [(T(8, 45), 1000, 1001, 999, 1000), (T(13, 25), 1000, 1100, 900, 1000)]
    assert run_day(bars, O, R) == []

    assert is_settlement_day(date(2024, 1, 17)) and not is_settlement_day(date(2024, 1, 10))
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?")
    ap.add_argument("--dt-col", default="datetime")
    ap.add_argument("--open-col", default="open")
    ap.add_argument("--high-col", default="high")
    ap.add_argument("--low-col", default="low")
    ap.add_argument("--close-col", default="close")
    ap.add_argument("--label", choices=["end", "start"], default="end",
                    help="K 棒時間戳是結束時間(預設,你的資料屬此)或開始時間")
    ap.add_argument("--cost", type=float, default=44)
    ap.add_argument("--cost-per", choices=["fill", "round"], default="fill",
                    help="fill=每次成交收 --cost(來回 2 次);round=每個來回收 --cost")
    ap.add_argument("--out", default="trades.csv")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.csv:
        ap.error("請提供 CSV 路徑")
    df = load(a.csv, a.dt_col, a.open_col, a.high_col, a.low_col, a.close_col, a.label)
    t = backtest(df, a.cost, a.cost_per)
    t.to_csv(a.out, index=False)
    print(summarize(t))
    print(f"逐筆明細:{a.out}")


if __name__ == "__main__":
    main()
