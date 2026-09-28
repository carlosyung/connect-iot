"""Daily original briefing ("今日重點") written by Claude from the day's headlines.

generate(data) writes content/briefings/YYYY-MM-DD.json once per HK day (needs
ANTHROPIC_API_KEY; skipped quietly without it). render(dist) turns every saved
briefing into dist/briefing/<date>.html plus an archive page and sitemap.
"""
import html
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
BRIEFINGS = Path(os.environ.get("BRIEFINGS_DIR", ROOT / "content" / "briefings"))
SITE = "https://connect-iot.com"
HKT = timezone(timedelta(hours=8))
MODEL = "claude-opus-5"
MAX_ARTICLES = 90
TOPICS = ["香港", "AI・LLM", "IoT", "科技", "財經", "國際"]
CAT_LABEL = {"hk": "香港", "ai": "AI", "iot": "IoT", "tech": "科技", "finance": "財經", "world": "國際"}

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "enum": TOPICS},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "headline": {"type": "string"},
                                "analysis": {"type": "string"},
                                "sources": {"type": "array", "items": {"type": "integer"}},
                            },
                            "required": ["headline", "analysis", "sources"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["topic", "items"],
                "additionalProperties": False,
            },
        },
        "takeaway": {"type": "string"},
        "en_summary": {"type": "string"},
    },
    "required": ["title", "summary", "sections", "takeaway", "en_summary"],
    "additionalProperties": False,
}

SYSTEM = """你是 Connect-IoT 的編輯，為香港讀者撰寫每日「今日重點」簡報，主題涵蓋香港本地新聞、AI 與大型語言模型、物聯網 (IoT)、科技、財經及國際要聞。

寫作要求：
- 用香港常用的繁體中文書面語，語氣專業、易讀；專有名詞可保留英文。
- 只根據提供的新聞列表內容撰寫，不可加入列表以外的事實、數字、人名或引述。資料不足時寫得保守一點，不要推測成事實。
- 每則重點用自己的文字重寫（不要照抄標題），analysis 用 2 至 4 句：先交代發生了甚麼，再說明對香港市民、企業或科技業界的意義。
- 挑選 6 至 10 則最值得香港讀者關注的新聞，分到合適的 topic；同一事件的多個來源合併為一則，sources 列出所有相關新聞的編號。
- title 是今日簡報的標題（30 字以內），summary 是 2 至 3 句導讀，takeaway 是一段 3 至 5 句的編輯觀點，en_summary 是 2 至 3 句英文摘要。"""


def today():
    return datetime.now(HKT).strftime("%Y-%m-%d")


def generate(data):
    """Write today's briefing if it doesn't exist yet. Never raises."""
    path = BRIEFINGS / f"{today()}.json"
    if path.exists():
        print(f"  briefing: {path.name} already exists")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  briefing: ANTHROPIC_API_KEY not set, skipped")
        return
    try:
        _generate(data, path)
    except Exception as e:  # a failed briefing must never block the daily news update
        print(f"  ! briefing failed: {type(e).__name__}: {e}", file=sys.stderr)


def _generate(data, path):
    import anthropic

    pool = sorted((a for a in data["articles"] if a["cat"] in CAT_LABEL),
                  key=lambda a: a.get("time") or "", reverse=True)[:MAX_ARTICLES]
    listing = "\n".join(
        f"[{i}] ({CAT_LABEL[a['cat']]}) {a['source']}｜{a['title']}" + (f"｜{a['summary']}" if a["summary"] else "")
        for i, a in enumerate(pool)
    )
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
        thinking={"type": "adaptive"},
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": f"今日日期：{today()}（香港時間）\n\n新聞列表：\n{listing}"}],
    )
    if response.stop_reason != "end_turn":
        print(f"  ! briefing: stop_reason={response.stop_reason}, skipped", file=sys.stderr)
        return
    text = next(b.text for b in response.content if b.type == "text")
    brief = json.loads(text)

    # Resolve source numbers to real links so the page never shows invented URLs
    for sec in brief["sections"]:
        for item in sec["items"]:
            item["sources"] = [{"title": pool[i]["title"], "source": pool[i]["source"], "link": pool[i]["link"]}
                               for i in dict.fromkeys(item["sources"]) if 0 <= i < len(pool)]
    brief["sections"] = [s for s in brief["sections"] if s["items"]]
    brief["date"] = today()
    brief["model"] = response.model
    BRIEFINGS.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    u = response.usage
    print(f"  briefing: wrote {path.name} ({u.input_tokens} in / {u.output_tokens} out tokens)")


def load_all():
    if not BRIEFINGS.exists():
        return []
    items = []
    for p in sorted(BRIEFINGS.glob("*.json"), reverse=True):
        try:
            items.append(json.loads(p.read_text(encoding="utf-8")))
        except ValueError:
            print(f"  ! skipping unreadable {p.name}", file=sys.stderr)
    return items


def homepage_card(briefings):
    """Small summary of the latest briefing for the homepage."""
    if not briefings:
        return None
    b = briefings[0]
    return {
        "date": b["date"], "title": b["title"], "summary": b["summary"], "url": f"briefing/{b['date']}",
        "points": [{"topic": s["topic"], "headline": i["headline"]} for s in b["sections"] for i in s["items"]][:6],
    }


# ---------- rendering ----------

e = html.escape

PAGE = """<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}｜Connect-IoT</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Noto+Sans+HK:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#eef2f7;--card:#fff;--text:#16202c;--muted:#5d6b7c;--line:#e3e8ef;--brand:#0a6cff;--soft:#f3f7ff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f141b;--card:#18202b;--text:#e7edf5;--muted:#98a6b8;--line:#273241;--brand:#5aa2ff;--soft:#1c2837}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font:17px/1.75 Inter,"Noto Sans HK","PingFang HK","Microsoft JhengHei",sans-serif}}
a{{color:var(--brand);text-decoration:none}} a:hover{{text-decoration:underline}}
header{{background:linear-gradient(135deg,#0a3d91,#0a6cff 45%,#00b3a4);color:#fff;padding:16px}}
header div{{max-width:760px;margin:0 auto;display:flex;align-items:center;gap:16px;font-weight:700}}
header a{{color:#fff}} header nav{{margin-left:auto;font-weight:500;font-size:15px;display:flex;gap:16px}}
main{{max-width:760px;margin:24px auto;padding:0 16px}}
article,.box{{background:var(--card);border-radius:14px;padding:28px}}
.kicker{{color:var(--brand);font-weight:600;font-size:14px;letter-spacing:.04em}}
h1{{font-size:28px;line-height:1.35;margin:6px 0 14px}}
h2{{font-size:19px;margin:32px 0 8px;padding-bottom:6px;border-bottom:2px solid var(--line)}}
h3{{font-size:17px;margin:18px 0 4px}}
p{{margin:0 0 10px}}
.lead{{font-size:18px;color:var(--muted)}}
.src{{font-size:13px;color:var(--muted);margin-top:-4px}}
.src a{{color:var(--muted);text-decoration:underline}}
.take{{background:var(--soft);border-left:4px solid var(--brand);padding:14px 18px;border-radius:8px;margin-top:28px}}
.en{{font-size:15px;color:var(--muted);border-top:1px solid var(--line);margin-top:24px;padding-top:14px}}
.note{{font-size:13px;color:var(--muted);margin-top:24px}}
ul.arch{{list-style:none;padding:0;margin:0}} ul.arch li{{padding:14px 0;border-bottom:1px solid var(--line)}}
ul.arch small{{display:block;color:var(--muted)}}
footer{{text-align:center;color:var(--muted);font-size:13px;padding:24px 16px 40px}}
</style>
</head>
<body>
<header><div><a href="/">Connect-IoT</a><nav><a href="/">首頁</a><a href="/briefing/">今日重點</a></nav></div></header>
<main>{body}</main>
<footer>© {year} Connect-IoT · 新聞版權屬原出處所有</footer>
</body>
</html>
"""


def fmt_date(d):
    dt = datetime.strptime(d, "%Y-%m-%d")
    return f"{dt.year} 年 {dt.month} 月 {dt.day} 日（{'一二三四五六日'[dt.weekday()]}）"


def page(title, desc, canonical, body):
    return PAGE.format(title=e(title), desc=e(desc), canonical=canonical, body=body, year=datetime.now(HKT).year)


def render_briefing(b):
    parts = [f'<article><div class="kicker">今日重點 · {fmt_date(b["date"])}</div>',
             f'<h1>{e(b["title"])}</h1><p class="lead">{e(b["summary"])}</p>']
    for sec in b["sections"]:
        parts.append(f'<h2>{e(sec["topic"])}</h2>')
        for item in sec["items"]:
            srcs = "、".join(f'<a href="{e(s["link"])}" target="_blank" rel="noopener">{e(s["source"])}</a>'
                            for s in item["sources"])
            parts.append(f'<h3>{e(item["headline"])}</h3><p>{e(item["analysis"])}</p>'
                         + (f'<p class="src">來源：{srcs}</p>' if srcs else ""))
    parts.append(f'<div class="take"><b>編輯觀點</b><p>{e(b["takeaway"])}</p></div>')
    parts.append(f'<p class="en"><b>In English:</b> {e(b["en_summary"])}</p>')
    parts.append('<p class="note">本文由 Connect-IoT 以 AI 輔助、根據當日公開新聞整理撰寫，詳情請參閱各原始報道。'
                 ' <a href="/briefing/">往期重點 →</a></p></article>')
    return page(b["title"], b["summary"], f"{SITE}/briefing/{b['date']}", "".join(parts))


def render_archive(briefings):
    rows = "".join(f'<li><a href="/briefing/{b["date"]}">{e(b["title"])}</a><small>{fmt_date(b["date"])} · {e(b["summary"])}</small></li>'
                   for b in briefings) or "<li>暫時未有內容</li>"
    body = f'<div class="box"><div class="kicker">ARCHIVE</div><h1>今日重點 · 往期</h1><ul class="arch">{rows}</ul></div>'
    return page("今日重點 · 往期", "Connect-IoT 每日香港、AI、IoT 及科技新聞重點與分析。", f"{SITE}/briefing/", body)


def render(dist, briefings):
    out = Path(dist) / "briefing"
    out.mkdir(parents=True, exist_ok=True)
    for b in briefings:
        (out / f"{b['date']}.html").write_text(render_briefing(b), encoding="utf-8")
    (out / "index.html").write_text(render_archive(briefings), encoding="utf-8")
    urls = [f"{SITE}/", f"{SITE}/briefing/"] + [f"{SITE}/briefing/{b['date']}" for b in briefings]
    (Path(dist) / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
    (Path(dist) / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n", encoding="utf-8")
