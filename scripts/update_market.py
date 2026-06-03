#!/usr/bin/env python3
import os, json, requests, datetime
from zoneinfo import ZoneInfo

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CLAUDE_KEY   = os.environ.get("CLAUDE_API_KEY", "")
GIST_ID      = os.environ.get("GIST_ID", "")
TW = ZoneInfo("Asia/Taipei")

TW_SYMBOLS = ["2330.TW","2317.TW","2449.TW","3189.TW","0050.TW","0056.TW"]
US_SYMBOLS = ["MSFT","NVDA","AAPL","GOOG","NOK","DRAM"]
NAMES = {
    "2330.TW":"台積電","2317.TW":"鴻海","2449.TW":"京元電子",
    "3189.TW":"景碩","0050.TW":"元大台灣50","0056.TW":"元大高股息",
    "MSFT":"Microsoft","NVDA":"NVIDIA","AAPL":"Apple",
    "GOOG":"Alphabet","NOK":"Nokia","DRAM":"Roundhill Mem ETF"
}

HEADERS_YAHOO = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

def fetch_quotes(symbols):
    """從 Yahoo Finance 抓取股票數據，失敗時逐筆重試"""
    results = []
    # Try all at once first
    try:
        s = ",".join(symbols)
        fields = "regularMarketPrice,regularMarketChange,regularMarketChangePercent,regularMarketOpen,regularMarketDayHigh,regularMarketDayLow,regularMarketVolume,trailingPE,dividendYield,shortName,regularMarketPreviousClose,fiftyDayAverage"
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={s}&fields={fields}"
        r = requests.get(url, headers=HEADERS_YAHOO, timeout=20)
        data = r.json().get("quoteResponse", {}).get("result", [])
        if data:
            print(f"  批次抓取成功: {len(data)} 筆")
            return data
    except Exception as e:
        print(f"  批次失敗: {e}")

    # Fallback: one by one
    print("  逐筆抓取...")
    for sym in symbols:
        for attempt in range(3):
            try:
                url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={sym}&fields=regularMarketPrice,regularMarketChange,regularMarketChangePercent,shortName,regularMarketPreviousClose,fiftyDayAverage,regularMarketOpen,regularMarketDayHigh,regularMarketDayLow,regularMarketVolume,trailingPE,dividendYield"
                r = requests.get(url, headers=HEADERS_YAHOO, timeout=15)
                q = r.json().get("quoteResponse", {}).get("result", [])
                if q:
                    results.append(q[0])
                    print(f"    ✓ {sym}: {q[0].get('regularMarketPrice','—')}")
                    break
            except Exception as e:
                print(f"    ✗ {sym} attempt {attempt+1}: {e}")
                import time; time.sleep(1)

    return results

def call_claude(prompt):
    """呼叫 Claude API"""
    if not CLAUDE_KEY:
        return "（未設定 CLAUDE_API_KEY）"
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 600,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=40
        )
        resp = r.json()
        # Debug output
        print(f"  Claude status: {r.status_code}")
        if r.status_code != 200:
            print(f"  Claude error: {resp}")
            return f"Claude API 錯誤 {r.status_code}: {resp.get('error',{}).get('message','unknown')}"
        content = resp.get("content", [])
        if not content:
            return "Claude 回傳空內容"
        return content[0].get("text", "（無文字回傳）")
    except Exception as e:
        return f"Claude 呼叫失敗: {e}"

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
    print(f"  結果: {len(tw)} 筆")

    print("\n[2] 抓美股...")
    us = fetch_quotes(US_SYMBOLS)
    print(f"  結果: {len(us)} 筆")

    # Build context strings
    def fmt_tw(q):
        p = q.get('regularMarketPrice', 0) or 0
        pct = q.get('regularMarketChangePercent', 0) or 0
        name = NAMES.get(q['symbol'], q.get('shortName', q['symbol']))
        return f"{name}: {p} ({'+' if pct>=0 else ''}{pct:.2f}%)"

    def fmt_us(q):
        p = q.get('regularMarketPrice', 0) or 0
        pct = q.get('regularMarketChangePercent', 0) or 0
        return f"{q['symbol']}: ${p} ({'+' if pct>=0 else ''}{pct:.2f}%)"

    tw_ctx = ", ".join([fmt_tw(q) for q in tw]) if tw else "（無法取得台股數據）"
    us_ctx = ", ".join([fmt_us(q) for q in us]) if us else "（無法取得美股數據）"
    slot_label = {"08:00": "開盤前快報", "12:00": "盤中分析", "17:00": "盤後總結"}[slot]

    print(f"\n[3] 呼叫 Claude 生成{slot_label}...")
    prompt = (
        f"你是台灣股市分析師，請生成今日{slot_label}。\n"
        f"台股：{tw_ctx}\n"
        f"美股：{us_ctx}\n"
        f"請用繁體中文200字以內分析：\n"
        f"1. 今日最強/最弱標的與原因\n"
        f"2. 主要驅動因子\n"
        f"3. 明日操作重點\n"
        f"語氣直接，重要數字用**粗體**標示。"
    )
    analysis = call_claude(prompt)
    print(f"  分析長度: {len(analysis)} 字")

    snapshot = {
        "ts": ts,
        "slot": slot,
        "tw": tw,
        "us": us,
        "analysis": analysis
    }

    print("\n[4] 寫入 Gist...")
    existing = read_gist()
    snaps = existing.get("snapshots", [])
    snaps.insert(0, snapshot)
    existing["snapshots"] = snaps[:9]
    existing["lastUpdated"] = ts
    if "slots" not in existing:
        existing["slots"] = {}
    existing["slots"][slot] = snapshot
    ok = write_gist(existing)
    print(f"  Gist 寫入: {'成功 ✓' if ok else '失敗 ✗'}")
    print("\n=== 完成 ===")

if __name__ == "__main__":
    main()
