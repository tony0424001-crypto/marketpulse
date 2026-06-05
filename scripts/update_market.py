#!/usr/bin/env python3
"""
MarketPulse 自動更新腳本 v3
- 08:00: 昨日美股收盤 + 開盤前新聞 + Groq AI 開盤前分析
- 12:00: 台股盤中行情 + 盤中新聞 + Groq AI 盤中分析  
- 17:00: 台股收盤 + 美股開盤前 + 盤後新聞 + Groq AI 盤後總結
"""
import os, json, requests, datetime, time, xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
GROQ_KEY     = os.environ.get("GROQ_KEY", "")
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

# ── 新聞來源（依時段不同）──
NEWS_SOURCES = {
    "08:00": [
        ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ("CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ],
    "12:00": [
        ("鉅亨網台股", "https://news.cnyes.com/rss/tw/stock.xml"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ],
    "17:00": [
        ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
        ("CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ]
}

def fetch_news(slot):
    """抓取指定時段的新聞 RSS"""
    sources = NEWS_SOURCES.get(slot, NEWS_SOURCES["17:00"])
    news = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MarketPulse/1.0)"}
    
    for source_name, url in sources:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            root = ET.fromstring(r.content)
            # Handle both RSS and Atom
            items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
            count = 0
            for item in items[:4]:
                title = (item.findtext('title') or 
                        item.findtext('{http://www.w3.org/2005/Atom}title') or '').strip()
                # Clean CDATA
                title = title.replace('<![CDATA[','').replace(']]>','').strip()
                if title and len(title) > 10:
                    # Try to get URL
                    url = (item.findtext('link') or
                           item.findtext('{http://www.w3.org/2005/Atom}link') or '')
                    # Handle link as element with href attribute
                    if not url:
                        link_el = item.find('link')
                        if link_el is not None:
                            url = link_el.get('href','') or link_el.text or ''
                    url = url.strip() if url else ''
                    news.append({
                        "source": source_name,
                        "title": title[:120],
                        "url": url[:300] if url.startswith('http') else '',
                        "time": datetime.datetime.now(TW).strftime("%H:%M"),
                        "slot": slot
                    })
                    count += 1
            print(f"    {source_name}: {count} 則")
        except Exception as e:
            print(f"    {source_name} 失敗: {e}")
    
    return news[:12]

def fetch_all_stocks(symbols):
    """用 yfinance 抓取股票數據 + 昨日分時"""
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
                
                # 今日 + 昨日分時
                intraday = t.history(period="2d", interval="5m")
                today_spark, prev_spark = [], []
                ma20 = None
                
                if not intraday.empty:
                    intraday.index = intraday.index.tz_convert(TW)
                    today = datetime.datetime.now(TW).date()
                    today_rows = intraday[intraday.index.date == today]
                    if not today_rows.empty:
                        today_spark = [round(p,2) for p in today_rows['Close'].tolist() if p==p]
                    for delta in range(1, 5):
                        prev_day = today - datetime.timedelta(days=delta)
                        prev_rows = intraday[intraday.index.date == prev_day]
                        if not prev_rows.empty:
                            prev_spark = [round(p,2) for p in prev_rows['Close'].tolist() if p==p]
                            if not prev_close:
                                prev_close = prev_spark[-1] if prev_spark else None
                            break
                
                # 月均線
                try:
                    hist = t.history(period="60d", interval="1d")
                    if not hist.empty and len(hist) >= 10:
                        closes = hist['Close'].tolist()
                        ma20 = round(sum(closes[-20:]) / min(len(closes),20), 2)
                    info = t.info
                    if info.get('fiftyDayAverage'):
                        ma20 = round(info['fiftyDayAverage'], 2)
                except: pass
                
                # Get extra info (PE, market cap)
                pe_ratio = None
                market_cap = None
                try:
                    info = t.info
                    pe_ratio = info.get('trailingPE') or info.get('forwardPE')
                    market_cap = info.get('marketCap')
                    if not ma20:
                        ma20 = info.get('fiftyDayAverage')
                except: pass
                # Fallback PE from fast_info
                if not pe_ratio:
                    pe_ratio = getattr(fi,'pe_ratio',None)
                
                results[sym] = {
                    "symbol": sym,
                    "shortName": NAMES.get(sym, sym),
                    "regularMarketPrice": round(price,2) if price else None,
                    "regularMarketChange": round(price-prev_close,2) if price and prev_close else 0,
                    "regularMarketChangePercent": round((price-prev_close)/prev_close*100,2) if price and prev_close else 0,
                    "regularMarketPreviousClose": round(prev_close,2) if prev_close else None,
                    "fiftyDayAverage": round(ma20,2) if ma20 else None,
                    "regularMarketOpen": round(getattr(fi,'open',price or 0) or price or 0, 2),
                    "regularMarketDayHigh": round(getattr(fi,'day_high',price or 0) or price or 0, 2),
                    "regularMarketDayLow": round(getattr(fi,'day_low',price or 0) or price or 0, 2),
                    "regularMarketVolume": int(getattr(fi,'three_month_average_volume',0) or 0),
                    "trailingPE": round(pe_ratio,2) if pe_ratio else None,
                    "marketCap": int(market_cap) if market_cap else None,
                    "dividendYield": getattr(fi,'dividend_yield',None),
                    "sparkPrices": today_spark,
                    "prevSparkPrices": prev_spark,
                }
                p = results[sym]['regularMarketPrice']
                pct = results[sym]['regularMarketChangePercent']
                print(f"    ✓ {sym}: {p} ({'+' if pct>=0 else ''}{pct:.2f}%) ma20={ma20}")
                time.sleep(0.4)
                break
            except Exception as e:
                if attempt == 0: time.sleep(1)
                else:
                    print(f"    ✗ {sym}: {e}")
                    results[sym] = {"symbol":sym,"shortName":NAMES.get(sym,sym),"regularMarketPrice":None,"regularMarketChangePercent":0,"sparkPrices":[],"prevSparkPrices":[]}
    return results

def call_groq(prompt, key):
    """呼叫 Groq API（免費）"""
    if not key:
        return "（未設定 GROQ_KEY）"
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "max_tokens": 600,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Groq 失敗: {e}"

def build_analysis(slot, tw, us, news):
    """依時段生成不同的 AI 分析"""
    now_str = datetime.datetime.now(TW).strftime("%Y-%m-%d %H:%M")
    
    tw_ctx = ", ".join([
        f"{NAMES.get(q['symbol'],q['symbol'])}: {q.get('regularMarketPrice','—')} ({'+' if (q.get('regularMarketChangePercent',0) or 0)>=0 else ''}{q.get('regularMarketChangePercent',0):.2f}%)"
        for q in tw if q.get('regularMarketPrice')
    ])
    us_ctx = ", ".join([
        f"{q['symbol']}: ${q.get('regularMarketPrice','—')} ({'+' if (q.get('regularMarketChangePercent',0) or 0)>=0 else ''}{q.get('regularMarketChangePercent',0):.2f}%)"
        for q in us if q.get('regularMarketPrice')
    ])
    news_ctx = "\n".join([f"- {n['source']}: {n['title']}" for n in news[:5]])
    
    if slot == "08:00":
        prompt = f"""你是台灣股市分析師，現在是{now_str}，台股即將開盤。

美股昨日收盤：{us_ctx}
今日重要新聞：
{news_ctx}

請用繁體中文200字以內生成「開盤前快報」，分析：
1. 美股昨日表現對今日台股的影響
2. 需要關注的重要消息面
3. 今日台股開盤方向預判
語氣直接，重要數字用**粗體**。"""

    elif slot == "12:00":
        prompt = f"""你是台灣股市分析師，現在是{now_str}台股盤中。

台股盤中：{tw_ctx}
美股昨收：{us_ctx}
盤中新聞：
{news_ctx}

請用繁體中文200字以內生成「盤中分析」，分析：
1. 目前盤面最強/最弱標的
2. 盤中主要驅動因子
3. 下午盤操作重點
語氣直接，重要數字用**粗體**。"""

    else:  # 17:00
        prompt = f"""你是台灣股市分析師，現在是{now_str}台股收盤後。

台股收盤：{tw_ctx}
美股：{us_ctx}
盤後新聞：
{news_ctx}

請用繁體中文200字以內生成「盤後總結」，分析：
1. 今日最強/最弱標的與原因
2. 主要驅動因子（法人、消息面）
3. 明日操作重點與觀察標的
語氣直接，重要數字用**粗體**。"""
    
    return prompt

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
        return {"snapshots":[], "news":[], "lastUpdated":"", "slots":{}}

def write_gist(data):
    r = requests.patch(
        f"https://api.github.com/gists/{GIST_ID}",
        headers={"Authorization": f"token {GITHUB_TOKEN}", "User-Agent": "MarketPulse", "Accept": "application/vnd.github+json"},
        json={"files":{"marketpulse_data.json":{"content":json.dumps(data, ensure_ascii=False, indent=2)}}},
        timeout=20
    )
    print(f"  write_gist: {r.status_code}")
    return r.status_code == 200

def main():
    now  = datetime.datetime.now(TW)
    h    = now.hour
    slot = "08:00" if h < 10 else "12:00" if h < 14 else "17:00"
    ts   = now.strftime("%Y-%m-%d %H:%M")
    slot_label = {"08:00":"開盤前快報","12:00":"盤中分析","17:00":"盤後總結"}[slot]
    print(f"=== MarketPulse {ts} CST — {slot_label} ===")

    print("\n[1] 抓取股票數據...")
    all_data = fetch_all_stocks(ALL_SYMBOLS)
    tw  = [all_data[s] for s in TW_SYMBOLS  if s in all_data]
    us  = [all_data[s] for s in US_SYMBOLS  if s in all_data]
    etf = [all_data[s] for s in ETF_SYMBOLS if s in all_data]
    print(f"  台股:{len([q for q in tw if q.get('regularMarketPrice')])}/6  美股:{len([q for q in us if q.get('regularMarketPrice')])}/6  ETF:{len([q for q in etf if q.get('regularMarketPrice')])}/10")

    print(f"\n[2] 抓取{slot_label}新聞...")
    news = fetch_news(slot)
    print(f"  共 {len(news)} 則新聞")

    print(f"\n[3] Groq AI 生成{slot_label}...")
    prompt = build_analysis(slot, tw, us, news)
    analysis = call_groq(prompt, GROQ_KEY)
    print(f"  分析完成 ({len(analysis)} 字)")

    snapshot = {"ts":ts, "slot":slot, "slotLabel":slot_label, "tw":tw, "us":us, "etf":etf, "news":news, "analysis":analysis}

    print("\n[4] 寫入 Gist...")
    existing = read_gist()
    snaps = existing.get("snapshots", [])
    snaps.insert(0, snapshot)
    existing["snapshots"] = snaps[:9]
    existing["lastUpdated"] = ts
    existing["latestNews"] = news
    existing.setdefault("slots", {})[slot] = snapshot
    ok = write_gist(existing)
    print(f"  {'✓ 成功' if ok else '✗ 失敗'}")
    print(f"\n=== 完成 ({slot_label}) ===")

if __name__ == "__main__":
    main()
