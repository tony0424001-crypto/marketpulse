#!/usr/bin/env python3
"""
MarketPulse - 使用 yfinance 抓取數據（處理 Yahoo Finance 反爬蟲）
Claude 分析由網頁端即時執行
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

def fetch_all_yfinance(symbols):
    """使用 yfinance 批次抓取"""
    import yfinance as yf
    results = {}
    
    print(f"  下載 {len(symbols)} 個標的...")
    try:
        # Batch download
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                t = tickers.tickers[sym]
                fi = t.fast_info
                hist = t.history(period="5d")
                
                price = getattr(fi, 'last_price', None)
                prev_close = getattr(fi, 'previous_close', None)
                ma50 = None
                spark = []
                
                if not hist.empty:
                    closes = hist['Close'].tolist()
                    if len(closes) >= 2:
                        prev_close = prev_close or closes[-2]
                    if len(closes) >= 10:
                        ma50 = sum(closes[-20:]) / min(len(closes), 20)
                # Try to get 50-day MA from info
                try:
                    info = t.info
                    if info.get('fiftyDayAverage'):
                        ma50 = info['fiftyDayAverage']
                except:
                    pass
                
                # Get today's intraday spark
                try:
                    intraday = t.history(period="1d", interval="5m")
                    if not intraday.empty:
                        spark = [round(p, 2) for p in intraday['Close'].tolist() if p == p]
                except:
                    pass
                
                results[sym] = {
                    "symbol": sym,
                    "shortName": NAMES.get(sym, getattr(fi, 'currency', sym)),
                    "regularMarketPrice": round(price, 2) if price else None,
                    "regularMarketChange": round(price - prev_close, 2) if price and prev_close else 0,
                    "regularMarketChangePercent": round((price - prev_close) / prev_close * 100, 2) if price and prev_close else 0,
                    "regularMarketPreviousClose": round(prev_close, 2) if prev_close else None,
                    "fiftyDayAverage": round(ma50, 2) if ma50 else None,
                    "regularMarketOpen": round(getattr(fi, 'open', price or 0), 2),
                    "regularMarketDayHigh": round(getattr(fi, 'day_high', price or 0), 2),
                    "regularMarketDayLow": round(getattr(fi, 'day_low', price or 0), 2),
                    "regularMarketVolume": int(getattr(fi, 'three_month_average_volume', 0) or 0),
                    "trailingPE": round(getattr(fi, 'pe_ratio', None) or 0, 2) or None,
                    "dividendYield": getattr(fi, 'dividend_yield', None),
                    "sparkPrices": spark
                }
                p = results[sym]['regularMarketPrice']
                pct = results[sym]['regularMarketChangePercent']
                print(f"    ✓ {sym}: {p} ({'+' if pct>=0 else ''}{pct:.2f}%)")
                time.sleep(0.3)
            except Exception as e:
                print(f"    ✗ {sym}: {e}")
                results[sym] = {"symbol": sym, "shortName": NAMES.get(sym, sym), "regularMarketPrice": None, "sparkPrices": []}
    except Exception as e:
        print(f"  批次失敗: {e}")
    
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
    now = datetime.datetime.now(TW)
    h = now.hour
    slot = "08:00" if h < 10 else "12:00" if h < 14 else "17:00"
    ts = now.strftime("%Y-%m-%d %H:%M")
    print(f"=== MarketPulse {ts} CST ({slot}) ===")

    print("\n[1] 抓取所有標的（yfinance）...")
    all_data = fetch_all_yfinance(ALL_SYMBOLS)

    tw  = [all_data[s] for s in TW_SYMBOLS  if s in all_data]
    us  = [all_data[s] for s in US_SYMBOLS  if s in all_data]
    etf = [all_data[s] for s in ETF_SYMBOLS if s in all_data]

    print(f"\n  台股: {len([q for q in tw  if q.get('regularMarketPrice')])}/{len(TW_SYMBOLS)} 筆有價格")
    print(f"  美股: {len([q for q in us  if q.get('regularMarketPrice')])}/{len(US_SYMBOLS)} 筆有價格")
    print(f"  ETF:  {len([q for q in etf if q.get('regularMarketPrice')])}/{len(ETF_SYMBOLS)} 筆有價格")

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
