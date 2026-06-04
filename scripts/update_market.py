#!/usr/bin/env python3
"""
MarketPulse - yfinance 版本
抓取今日+昨日分時走勢、月均線，存入 Gist
"""
import os, json, requests, datetime, time
from zoneinfo import ZoneInfo

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
TW = ZoneInfo("Asia/Taipei")

TW_SYMBOLS  = ["2330.TW","2317.TW","2449.TW","3189.TW","0050.TW","0056.TW"]
US_SYMBOLS  = ["MSFT","NVDA","AAPL","GOOG","NOK","DRAM"]
ETF_SYMBOLS = ["0050.TW","0056.TW","00878.TW","00919.TW","006208.TW",
               "00881.TW","00646.TW","00929.TW","00757.TW","00900.TW"]
ALL_SYMBOLS = list(dict.fromkeys(TW_SYMBOLS + US_SYMBOLS + ETF_SYMBOLS))

NAMES = {
    "2330.TW":"台積電","2317.TW":"鴻海","2449.TW":"京元電子",
    "3189.TW":"景碩","0050.TW":"元大台灣50","0056.TW":"元大高股息",
    "MSFT":"Microsoft","NVDA":"NVIDIA","AAPL":"Apple",
    "GOOG":"Alphabet","NOK":"Nokia","DRAM":"Roundhill Mem ETF"
}

def fetch_all(symbols):
    import yfinance as yf
    results = {}
    print(f"  抓取 {len(symbols)} 個標的...")
    
    for sym in symbols:
        for attempt in range(2):
            try:
                t = yf.Ticker(sym)
                fi = t.fast_info

                price      = getattr(fi, 'last_price', None)
                prev_close = getattr(fi, 'previous_close', None)
                
                # 用 2d 5m 同時取今日和昨日分時數據
                intraday = t.history(period="2d", interval="5m")
                
                today_spark = []
                prev_spark  = []
                ma20        = None
                
                if not intraday.empty:
                    intraday.index = intraday.index.tz_convert(TW)
                    today = datetime.datetime.now(TW).date()
                    yesterday = today - datetime.timedelta(days=1)
                    # 往前找最近的交易日
                    for delta in range(1, 5):
                        prev_day = today - datetime.timedelta(days=delta)
                        prev_rows = intraday[intraday.index.date == prev_day]
                        if not prev_rows.empty:
                            prev_spark = [round(p,2) for p in prev_rows['Close'].tolist() if p==p]
                            if not prev_close:
                                prev_close = prev_spark[-1] if prev_spark else None
                            break
                    
                    today_rows = intraday[intraday.index.date == today]
                    if not today_rows.empty:
                        today_spark = [round(p,2) for p in today_rows['Close'].tolist() if p==p]
                
                # 月均線：用 60 天日K 計算 20MA
                try:
                    hist60 = t.history(period="60d", interval="1d")
                    if not hist60.empty and len(hist60) >= 10:
                        closes = hist60['Close'].tolist()
                        ma20 = round(sum(closes[-20:]) / min(len(closes), 20), 2)
                except:
                    pass
                
                # 如果 fast_info 有 fiftyDayAverage 用那個（更準確）
                try:
                    info = t.info
                    if info.get('fiftyDayAverage'):
                        ma20 = round(info['fiftyDayAverage'], 2)
                except:
                    pass

                results[sym] = {
                    "symbol": sym,
                    "shortName": NAMES.get(sym, getattr(fi, 'currency', sym)),
                    "regularMarketPrice": round(price, 2) if price else None,
                    "regularMarketChange": round(price - prev_close, 2) if price and prev_close else 0,
                    "regularMarketChangePercent": round((price - prev_close) / prev_close * 100, 2) if price and prev_close else 0,
                    "regularMarketPreviousClose": round(prev_close, 2) if prev_close else None,
                    "fiftyDayAverage": ma20,
                    "regularMarketOpen": round(getattr(fi, 'open', price or 0) or price or 0, 2),
                    "regularMarketDayHigh": round(getattr(fi, 'day_high', price or 0) or price or 0, 2),
                    "regularMarketDayLow": round(getattr(fi, 'day_low', price or 0) or price or 0, 2),
                    "regularMarketVolume": int(getattr(fi, 'three_month_average_volume', 0) or 0),
                    "trailingPE": round(getattr(fi, 'pe_ratio', None) or 0, 2) or None,
                    "dividendYield": getattr(fi, 'dividend_yield', None),
                    "sparkPrices": today_spark,    # 今日分時
                    "prevSparkPrices": prev_spark,  # 昨日分時（新增）
                }
                
                p   = results[sym]['regularMarketPrice']
                pct = results[sym]['regularMarketChangePercent']
                ma_str = f" MA20={ma20}" if ma20 else ""
                prev_str = f" prev={len(prev_spark)}pts" if prev_spark else ""
                print(f"    ✓ {sym}: {p} ({'+' if pct>=0 else ''}{pct:.2f}%){ma_str}{prev_str}")
                time.sleep(0.4)
                break
                
            except Exception as e:
                if attempt == 0:
                    time.sleep(1)
                else:
                    print(f"    ✗ {sym}: {e}")
                    results[sym] = {
                        "symbol": sym, "shortName": NAMES.get(sym, sym),
                        "regularMarketPrice": None, "regularMarketChangePercent": 0,
                        "sparkPrices": [], "prevSparkPrices": []
                    }
    return results

def read_gist():
    try:
        r = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={"Authorization": f"token {GITHUB_TOKEN}", "User-Agent": "MarketPulse", "Accept": "application/vnd.github+json"},
            timeout=15
        )
        content = r.json()["files"]["marketpulse_data.json"]["content"]
        return json.loads(content)
    except Exception as e:
        print(f"  read_gist error: {e}")
        return {"snapshots": [], "news": [], "lastUpdated": "", "slots": {}}

def write_gist(data):
    r = requests.patch(
        f"https://api.github.com/gists/{GIST_ID}",
        headers={"Authorization": f"token {GITHUB_TOKEN}", "User-Agent": "MarketPulse", "Accept": "application/vnd.github+json"},
        json={"files": {"marketpulse_data.json": {"content": json.dumps(data, ensure_ascii=False, indent=2)}}},
        timeout=20
    )
    print(f"  write_gist: {r.status_code}")
    return r.status_code == 200

def main():
    now  = datetime.datetime.now(TW)
    h    = now.hour
    slot = "08:00" if h < 10 else "12:00" if h < 14 else "17:00"
    ts   = now.strftime("%Y-%m-%d %H:%M")
    print(f"=== MarketPulse {ts} CST ({slot}) ===")

    print("\n[1] 抓取所有標的...")
    all_data = fetch_all(ALL_SYMBOLS)

    tw  = [all_data[s] for s in TW_SYMBOLS  if s in all_data]
    us  = [all_data[s] for s in US_SYMBOLS  if s in all_data]
    etf = [all_data[s] for s in ETF_SYMBOLS if s in all_data]

    tw_ok  = len([q for q in tw  if q.get('regularMarketPrice')])
    us_ok  = len([q for q in us  if q.get('regularMarketPrice')])
    etf_ok = len([q for q in etf if q.get('regularMarketPrice')])
    ma_ok  = len([q for q in tw+us if q.get('fiftyDayAverage')])
    prev_ok= len([q for q in tw+us if q.get('prevSparkPrices')])
    print(f"\n  台股: {tw_ok}/6  美股: {us_ok}/6  ETF: {etf_ok}/10")
    print(f"  月均線: {ma_ok}/12  昨日分時: {prev_ok}/12")

    snapshot = {"ts": ts, "slot": slot, "tw": tw, "us": us, "etf": etf, "analysis": ""}

    print("\n[2] 寫入 Gist...")
    existing = read_gist()
    snaps = existing.get("snapshots", [])
    snaps.insert(0, snapshot)
    existing["snapshots"] = snaps[:9]
    existing["lastUpdated"] = ts
    existing.setdefault("slots", {})[slot] = snapshot
    ok = write_gist(existing)
    print(f"  {'✓ 成功' if ok else '✗ 失敗'}")
    print("\n=== 完成 ===")

if __name__ == "__main__":
    main()
