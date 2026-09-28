#!/usr/bin/env python3
"""Build the Connect-IoT homepage.

Fetches news feeds, weather and market data, then writes dist/index.html
(template.html with the data inlined) and dist/data.json.
Standard library only, so it runs anywhere Python 3.9+ is installed.
"""
import html
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import briefing

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
HKT = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (compatible; ConnectIoTBot/1.0; +https://connect-iot.com)"

# (category, source label, url, max items)
FEEDS = [
    ("hk", "香港電台", "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", 15),
    ("hk", "RTHK English", "https://rthk.hk/rthk/news/rss/e_expressnews_elocal.xml", 10),
    ("hk", "Google 新聞", "https://news.google.com/rss?hl=zh-HK&gl=HK&ceid=HK:zh-Hant", 20),
    ("ai", "TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", 12),
    ("ai", "Hugging Face", "https://huggingface.co/blog/feed.xml", 6),
    ("ai", "Google 新聞", "https://news.google.com/rss/search?q=AI+OR+LLM+OR+%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD&hl=zh-HK&gl=HK&ceid=HK:zh-Hant", 12),
    ("iot", "IoT Business News", "https://iotbusinessnews.com/feed/", 12),
    ("iot", "Google News", "https://news.google.com/rss/search?q=IoT+OR+%22Internet+of+Things%22+when:3d&hl=en-HK&gl=HK&ceid=HK:en", 12),
    ("iot", "Google 新聞", "https://news.google.com/rss/search?q=%E7%89%A9%E8%81%AF%E7%B6%B2+OR+%E6%99%BA%E6%85%A7%E5%9F%8E%E5%B8%82&hl=zh-HK&gl=HK&ceid=HK:zh-Hant", 8),
    ("tech", "unwire.hk", "https://unwire.hk/feed/", 12),
    ("tech", "The Verge", "https://www.theverge.com/rss/index.xml", 12),
    ("tech", "TechCrunch", "https://techcrunch.com/feed/", 10),
    ("tech", "Hacker News", "https://hnrss.org/frontpage", 12),
    ("finance", "香港電台", "https://rthk.hk/rthk/news/rss/c_expressnews_cfinance.xml", 12),
    ("world", "香港電台", "https://rthk.hk/rthk/news/rss/c_expressnews_cinternational.xml", 12),
    ("gov", "政府新聞公報", "https://www.info.gov.hk/gia/rss/general_zh.xml", 10),
]

MARKETS = [
    ("^HSI", "恒生指數"),
    ("^GSPC", "標普 500"),
    ("^IXIC", "納斯達克"),
    ("0700.HK", "騰訊控股"),
    ("9988.HK", "阿里巴巴"),
    ("BTC-USD", "Bitcoin"),
]

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


def fetch(url, limit=None, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-HK,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit) if limit else r.read()


def clean(text, max_len=None):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if max_len and len(text) > max_len:
        text = text[:max_len].rstrip() + "…"
    return text


def safe_url(u):
    u = (u or "").strip()
    return u if u.startswith(("https://", "http://")) else ""


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def find_image(el, raw_html):
    for tag in ("media:content", "media:thumbnail"):
        for m in el.findall(tag, NS):
            if m.get("url") and m.get("medium", "image") == "image":
                return m.get("url")
    for enc in el.findall("enclosure"):
        if (enc.get("type") or "").startswith("image") and enc.get("url"):
            return enc.get("url")
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_html or "")
    return html.unescape(m.group(1)) if m else ""


def parse_feed(cat, source, url, limit):
    root = ET.fromstring(fetch(url))
    out = []
    items = root.findall(".//item") or root.findall("atom:entry", NS)
    for el in items[:limit]:
        is_atom = el.tag.endswith("entry")
        if is_atom:
            title = el.findtext("atom:title", "", NS)
            link_el = el.find("atom:link[@rel='alternate']", NS)
            if link_el is None:
                link_el = el.find("atom:link", NS)
            link = link_el.get("href") if link_el is not None else ""
            body = el.findtext("atom:content", "", NS) or el.findtext("atom:summary", "", NS)
            date = el.findtext("atom:published", "", NS) or el.findtext("atom:updated", "", NS)
        else:
            title = el.findtext("title", "")
            link = el.findtext("link", "")
            body = el.findtext("content:encoded", "", NS) or el.findtext("description", "")
            date = el.findtext("pubDate", "")
        src = source
        title = clean(title)
        # Google News titles end with " - Publisher"
        if "news.google.com" in url and " - " in title:
            title, src = title.rsplit(" - ", 1)
        link = safe_url(link)
        if not title or not link:
            continue
        d = parse_date(date)
        out.append({
            "cat": cat,
            "source": src,
            "title": title,
            "summary": "" if "news.google.com" in url else clean(body, 160),
            "link": link,
            "image": safe_url(find_image(el, body)),
            "time": d.isoformat() if d else "",
        })
    return out


def og_image(item):
    try:
        page = fetch(item["link"], limit=300_000, timeout=8).decode("utf-8", "ignore")
    except Exception:
        return
    m = re.search(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)', page) or \
        re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image', page)
    if m:
        item["image"] = safe_url(html.unescape(m.group(1)))


def get_weather():
    base = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?lang=tc&dataType="
    now = json.loads(fetch(base + "rhrread"))
    fnd = json.loads(fetch(base + "fnd"))
    temp = next((t["value"] for t in now["temperature"]["data"] if t["place"] == "香港天文台"),
                now["temperature"]["data"][0]["value"])
    return {
        "temp": temp,
        "humidity": now["humidity"]["data"][0]["value"],
        "icon": (now.get("icon") or [50])[0],
        "warning": [w for w in (now.get("warningMessage") or []) if w],
        "situation": fnd.get("generalSituation", ""),
        "forecast": [{
            "date": f["forecastDate"],
            "week": f["week"],
            "min": f["forecastMintemp"]["value"],
            "max": f["forecastMaxtemp"]["value"],
            "icon": f["ForecastIcon"],
            "text": f["forecastWeather"],
        } for f in fnd["weatherForecast"][:7]],
    }


def get_quote(symbol_name):
    symbol, name = symbol_name
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1mo&interval=1d"
    res = json.loads(fetch(url))["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    price = res["meta"]["regularMarketPrice"]
    prev = closes[-2] if len(closes) > 1 else price
    return {
        "symbol": symbol, "name": name, "price": price,
        "change": (price - prev) / prev * 100 if prev else 0,
        "spark": [round(c, 2) for c in closes[-20:]],
    }


def get_fx():
    rates = json.loads(fetch("https://open.er-api.com/v6/latest/HKD"))["rates"]
    return [{"code": c, "rate": 1 / rates[c]} for c in ("USD", "CNY", "JPY", "EUR", "GBP") if rates.get(c)]


def safe(fn, *args, default=None):
    try:
        return fn(*args)
    except Exception as e:
        print(f"  ! {fn.__name__}{args[:2]}: {e}", file=sys.stderr)
        return default


def main():
    with ThreadPoolExecutor(12) as pool:
        feed_jobs = [pool.submit(safe, parse_feed, *f, default=[]) for f in FEEDS]
        weather_job = pool.submit(safe, get_weather)
        market_jobs = [pool.submit(safe, get_quote, m) for m in MARKETS]
        fx_job = pool.submit(safe, get_fx, default=[])

        articles, seen = [], set()
        for (cat, source, *_), job in zip(FEEDS, feed_jobs):
            items = job.result()
            print(f"  {cat:8} {source:18} {len(items)} items")
            for it in items:
                key = re.sub(r"\W", "", it["title"].lower())[:40]
                if key not in seen:
                    seen.add(key)
                    articles.append(it)

        # Fill in missing images from the article page (skip Google News redirect links)
        need = [a for a in articles if not a["image"] and "news.google.com" not in a["link"]][:60]
        list(pool.map(og_image, need))

        data = {
            "updated": datetime.now(HKT).isoformat(timespec="minutes"),
            "articles": articles,
            "weather": weather_job.result(),
            "markets": [q for q in (j.result() for j in market_jobs) if q],
            "fx": fx_job.result(),
        }

    if len(articles) < 20:
        sys.exit(f"Only {len(articles)} articles fetched; refusing to publish a near-empty page.")

    briefing.generate(data)
    briefings = briefing.load_all()
    data["briefing"] = briefing.homepage_card(briefings)

    shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir()
    briefing.render(DIST, briefings)
    payload = json.dumps(data, ensure_ascii=False)
    (DIST / "data.json").write_text(payload, encoding="utf-8")
    page = (ROOT / "template.html").read_text(encoding="utf-8")
    # Escape "</" so feed text can never close the inline <script>
    page = page.replace("/*__DATA__*/null", payload.replace("</", "<\\/"))
    (DIST / "index.html").write_text(page, encoding="utf-8")
    for extra in ("favicon.svg",):
        if (ROOT / extra).exists():
            shutil.copy(ROOT / extra, DIST / extra)
    print(f"Built {len(articles)} articles, {len(data['markets'])} quotes, {len(briefings)} briefings -> {DIST}")


if __name__ == "__main__":
    main()
