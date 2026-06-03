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

def fetch_quotes(symbols):
    s = ",".join(symbols)
    fields = "regularMarketPrice,regularMarketChange,regularMarketChangePercent,regularMarketOpen,regularMarketDayHigh,regularMarketDayLow,regularMarketVolume,trailingPE,dividendYield,shortName,regularMarketPreviousClose,fiftyDayAverage"
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={s}&fields={fields}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        return r.json().get("quoteResponse", {}).get("result", [])
    except Exception as e:
        print(f"fetch error: {e}")
        return []

def call_claude(prompt):
    if not CLAUDE_KEY:
        return "（未設定 Claude API Key）"
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
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        return r.json()["content"][0]["text"]
    except Exception as e:
        return f"Claude 失敗: {e}"

def read_gist():
    try:
        r = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={"Authorization": f"token {GITHUB_TOKEN}", "User-Agent": "MarketPulse"}
        )
        content = r.json()["files"]["marketpulse_data.json"]["content"]
        return json.loads(content)
    except:
        return {"snapshots": [], "news": [], "lastUpdated": "", "slots": {}}

def write_gist(data):
    r = requests.patch(
        f"https://api.github.com/gists/{GIST_ID}",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "User-Agent": "MarketPulse",
            "Accept": "application/vnd.github+json"
        },
        json={"files": {"marketpulse_data.json": {"content": json.dumps(data, ensure_ascii=False, indent=2)}}}
    )
    return r.status_code == 200

def main():
    now = datetime.datetime.now(TW)
    h = now.hour
    slot = "08:00" if h < 10 else "12:00" if h < 14 else "17:00"
    ts = now.strftime("%Y-%m-%d %H:%M")
    print(f"=== {ts} CST ({slot}) ===")

    print("抓台股...")
    tw = fetch_quotes(TW_SYMBOLS)
    print(f"  {len(tw)} 筆")

    print("抓美股...")
    us = fetch_quotes(US_SYMBOLS)
    print(f"  {len(us)} 筆")

    tw_ctx = ", ".join([f"{NAMES.get(q['symbol'],q['symbol'])}: {q.get('regularMarketPrice','—')} ({'+' if (q.get('regularMarketChangePercent',0) or 0)>=0 else ''}{q.get('regularMarketChangePercent',0):.2f}%)" for q in tw])
    us_ctx = ", ".join([f"{q['symbol']}: ${q.get('regularMarketPrice','—')} ({'+' if (q.get('regularMarketChangePercent',0) or 0)>=0 else ''}{q.get('regularMarketChangePercent',0):.2f}%)" for q in us])
    slot_label = {"08:00":"開盤前快報","12:00":"盤中分析","17:00":"盤後總結"}[slot]

    print("呼叫 Claude...")
    analysis = call_claude(f"""你是台灣股市分析師，請生成今日{slot_label}：
台股：{tw_ctx}
美股：{us_ctx}
請用繁體中文250字以內分析：
1. 今日最強/最弱標的與原因
2. 主要驅動因子
3. 操作建議與明日觀察重點
語氣直接，數字用**粗體**。""")
    print(f"  完成 ({len(analysis)} 字)")

    snapshot = {"ts": ts, "slot": slot, "tw": tw, "us": us, "analysis": analysis}

    print("寫入 Gist...")
    existing = read_gist()
    snaps = existing.get("snapshots", [])
    snaps.insert(0, snapshot)
    existing["snapshots"] = snaps[:9]
    existing["lastUpdated"] = ts
    existing["slots"][slot] = snapshot
    ok = write_gist(existing)
    print(f"  {'成功' if ok else '失敗'}")
    print("=== 完成 ===")

if __name__ == "__main__":
    main()
