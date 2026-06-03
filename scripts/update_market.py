#!/usr/bin/env python3
"""
MarketPulse 自動更新腳本
- 抓取台股/美股即時數據存入 Gist
- Claude 分析改在網頁端即時執行（不需要 API 餘額）
"""
import os, json, requests, datetime
from zoneinfo import ZoneInfo

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
TW = ZoneInfo("Asia/Taipei")

TW_SYMBOLS = ["2330.TW","2317.TW","2449.TW","3189.TW","0050.TW","0056.TW"]
US_SYMBOLS = ["MSFT","NVDA","AAPL","GOOG","NOK","DRAM"]
ETF_SYMBOLS = ["0050.TW","0056.TW","00878.TW","00919.TW","006208.TW",
               "00881.TW","00646.TW","00929.TW","00757.TW","00900.TW"]
NAMES = {
    "2330.TW":"台積電","2317.TW":"鴻海","2449.TW":"京元電子",
    "3189.TW":"景碩","0050.TW":"元大台灣50","0056.TW":"元大高股息",
    "MSFT":"Microsoft","NVDA":"NVIDIA","AAPL":"Apple",
    "GOOG":"Alphabet","NOK":"Nokia","DRAM":"Roundhill Mem ETF"
}

# 多個 User-Agent 輪替，避免被擋
UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

def get_headers(idx=0):
    return {
        "User-Agent": UA_LIST[idx % len(UA_LIST)],
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://finance.yahoo.com/",
        "Origin": "https://finance.yahoo.com",
    }

def fetch_quotes(symbols, attempt=0):
    """抓取股票數據，多個端點輪替"""
    fields = "regularMarketPrice,regularMarketChange,regularMarketChangePercent,regularMarketOpen,regularMarketDayHigh,regularMarketDayLow,regularMarketVolume,trailingPE,dividendYield,shortName,regularMarketPreviousClose,fiftyDayAverage"
    s = ",".join(symbols)

    # 嘗試多個 Yahoo Finance 端點
    endpoints = [
        f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={s}&fields={fields}",
        f"https://query2.finance.yahoo.com/v7/finance/quote?symbols={s}&fields={fields}",
        f"https://query1.finance.yahoo.com/v8/finance/quote?symbols={s}&fields={fields}",
    ]

    for i, url in enumerate(endpoints):
        try:
            r = requests.get(url, headers=get_headers(i), timeout=20)
            print(f"  端點{i+1} status: {r.status_code}")
            if r.status_code == 200:
                data = r.json().get("quoteResponse", {}).get("result", [])
                if data:
                    print(f"  ✓ 成功抓到 {len(data)} 筆")
                    return data
        except Exception as e:
            print(f"  端點{i+1} 失敗: {e}")

    # 所有端點失敗，逐筆嘗試
    print("  批次失敗，逐筆嘗試...")
    results = []
    for sym in symbols:
        for ep_idx in range(2):
            try:
                url = f"https://query{ep_idx+1}.finance.yahoo.com/v7/finance/quote?symbols={sym}&fields={fields}"
                r = requests.get(url, headers=get_headers(ep_idx), timeout=15)
                q = r.json().get("quoteResponse", {}).get("result", [])
                if q:
                    results.append(q[0])
                    print(f"    ✓ {sym}: {q[0].get('regularMarketPrice','—')}")
                    break
            except:
                pass
        import time; time.sleep(0.5)
    return results

def fetch_spark(symbols):
    """抓取分時走勢數據"""
    s = ",".join(symbols)
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/spark?symbols={s}&range=1d&interval=5m"
        r = requests.get(url, headers=get_headers(), timeout=15)
        sparks = {}
        data = r.json().get("spark", {}).get("result", [])
        for item in data:
            sym = item.get("symbol")
            prices = item.get("response", [{}])[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            sparks[sym] = [p for p in prices if p is not None]
        return sparks
    except Exception as e:
        print(f"  spark 失敗: {e}")
        return {}

def read_gist():
    try:
        r = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "User-Agent": "MarketPulse",
                "Accept": "application/vnd.github+json"
            },
            timeout=15
        )
        files = r.json().get("files", {})
        content = files.get("marketpulse_data.json", {}).get("content", "{}")
        return json.loads(content)
    except Exception as e:
        print(f"  read_gist error: {e}")
        return {"snapshots": [], "news": [], "lastUpdated": "", "slots": {}}

def write_gist(data):
    r = requests.patch(
        f"https://api.github.com/gists/{GIST_ID}",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "User-Agent": "MarketPulse",
            "Accept": "application/vnd.github+json"
        },
        json={
            "files": {
                "marketpulse_data.json": {
                    "content": json.dumps(data, ensure_ascii=False, indent=2)
                }
            }
        },
        timeout=15
    )
    print(f"  write_gist status: {r.status_code}")
    return r.status_code == 200

def main():
    now = datetime.datetime.now(TW)
    h = now.hour
    slot = "08:00" if h < 10 else "12:00" if h < 14 else "17:00"
    ts = now.strftime("%Y-%m-%d %H:%M")
    print(f"=== MarketPulse {ts} CST ({slot}) ===")

    print("\n[1] 抓台股...")
    tw = fetch_quotes(TW_SYMBOLS)
    print(f"  台股: {len(tw)} 筆")

    print("\n[2] 抓美股...")
    us = fetch_quotes(US_SYMBOLS)
    print(f"  美股: {len(us)} 筆")

    print("\n[3] 抓 ETF...")
    etf = fetch_quotes(ETF_SYMBOLS)
    print(f"  ETF: {len(etf)} 筆")

    print("\n[4] 抓分時走勢...")
    all_syms = TW_SYMBOLS + US_SYMBOLS
    sparks = fetch_spark(all_syms)
    print(f"  走勢: {len(sparks)} 筆")

    # 把 sparkPrices 合併進 quotes
    def merge_spark(quotes, sparks):
        for q in quotes:
            q["sparkPrices"] = sparks.get(q.get("symbol", ""), [])
        return quotes

    tw = merge_spark(tw, sparks)
    us = merge_spark(us, sparks)

    # 組成快照（不含 Claude 分析，由網頁端即時呼叫）
    snapshot = {
        "ts": ts,
        "slot": slot,
        "tw": tw,
        "us": us,
        "etf": etf,
        "analysis": ""  # 網頁端即時生成
    }

    print("\n[5] 寫入 Gist...")
    existing = read_gist()
    snaps = existing.get("snapshots", [])
    snaps.insert(0, snapshot)
    existing["snapshots"] = snaps[:9]
    existing["lastUpdated"] = ts
    if "slots" not in existing:
        existing["slots"] = {}
    existing["slots"][slot] = snapshot

    ok = write_gist(existing)
    print(f"  結果: {'✓ 成功' if ok else '✗ 失敗'}")

    # 統計
    print(f"\n=== 完成 ===")
    print(f"  台股: {len(tw)} 筆, 美股: {len(us)} 筆, ETF: {len(etf)} 筆")
    print(f"  Claude 分析: 由網頁端即時執行（不需要伺服器端 API 餘額）")

if __name__ == "__main__":
    main()
