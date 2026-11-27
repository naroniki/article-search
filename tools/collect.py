#!/usr/bin/env python3
"""週次ネタ集め: 対象誌の記事見出しを集めて candidates/YYYY-MM-DD.md に書き出す(標準ライブラリのみ)。

  python3 tools/collect.py                 # 全部(10〜15分かかる)
  python3 tools/collect.py --only fujisan  # Fujisanの最新号目次だけ
  python3 tools/collect.py --only ndl --months 2

- 国会図書館: 雑誌名で検索し、直近Nか月に索引された記事を取得(記事ごとの書誌URLつき)
- Fujisan: 最新号ページの目次(見出し・要約・ページ)を取得(URLは号のページ)
- picks/ に既に載っているURLの記事は「済」として除外
- どちらのサイトも連続アクセスで 429 を返すので、間隔をあけ、429なら待って再試行する
"""
import argparse, datetime, glob, html, json, os, re, sys, time
import urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (neta-lab)"}
NS = {"dc": "http://purl.org/dc/elements/1.1/", "dcndl": "http://ndl.go.jp/dcndl/terms/"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url, gap, tries=6):
    """GETして本文を返す。429/5xx/タイムアウトは待って再試行。最後はNone。"""
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                body = r.read()
            time.sleep(gap)
            return body
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                log("  HTTP", e.code, url); return None
            log("  HTTP", e.code, "-> 待って再試行", i + 1)
        except Exception as e:
            if "403" in str(e):
                log("  接続拒否(ネットワーク設定でホスト未許可?)", e); return None
            log("  ERR", e, "-> 再試行", i + 1)
        time.sleep(gap + 15 * (i + 1))
    return None


def ndl(src, since):
    q = urllib.parse.urlencode({"any": src["query"], "from": since, "cnt": "500"})
    body = get("https://ndlsearch.ndl.go.jp/api/opensearch?" + q, gap=12)
    if body is None:
        return None
    out = []
    for it in ET.fromstring(body).iter("item"):
        cats = [c.text for c in it.findall("category")]
        desc = " ".join(d.text or "" for d in it.findall("dc:description", NS))
        m = re.search(r"掲載誌：(.*)", desc)
        if "記事" not in cats or not m or src["match"] not in m.group(1):
            continue
        ser = it.findtext("dcndl:seriesTitle", "", NS)
        out.append({
            "title": (it.findtext("title") or "").strip(),
            "section": ser.split(" ; ")[0] if ser else "",
            "issue": re.sub(r"\s+p\.[\d\-]+$", "", m.group(1)).split(" = ")[-1],
            "url": (it.findtext("link") or "").strip(),
        })
    return out


def fujisan(src):
    url = "https://www.fujisan.co.jp/product/%s/new/" % src["id"]
    body = get(url, gap=6)
    if body is None:
        return None, None, url
    s = body.decode("utf-8", "replace")
    issue, toc = "", ""
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', s, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict) and d.get("@type") == "Product" and d.get("description"):
                issue, toc = d.get("name", ""), d["description"]
    canon = re.search(r'<link rel="canonical" href="([^"]+)"', s)
    page = canon.group(1) if canon else url
    toc = html.unescape(toc)
    if "の雑誌を販売中" in toc:  # 目次のない定型文
        toc = ""
    if "●" not in toc:  # ■●形式でない目次は、注意書きを除いて本文のまま返す
        text = re.sub(r"※.*?(?:ございます。|ません。|です。)", "", toc).strip()
        return ([{"raw": text[:2000]}] if text else []), issue, page
    out, section = [], ""
    for part in re.split(r"(?=[■●])", toc):
        part = part.strip()
        if part.startswith("■"):
            section = part[1:].strip()[:60]
        elif part.startswith("●"):
            out.append({"title": part[1:].strip(), "section": section, "issue": issue, "url": page})
    return out, issue, page


def picked_urls():
    urls = set()
    for f in glob.glob(os.path.join(ROOT, "picks", "*.md")):
        urls |= set(re.findall(r"https?://\S+", open(f, encoding="utf-8").read()))
    return urls


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", choices=["ndl", "fujisan"])
    p.add_argument("--months", type=int, default=2, help="国会図書館: 何か月前の月初から")
    p.add_argument("--out")
    a = p.parse_args()
    srcs = json.load(open(os.path.join(ROOT, "tools", "sources.json"), encoding="utf-8"))
    today = datetime.date.today()
    y, m = today.year, today.month - a.months
    while m <= 0:
        y, m = y - 1, m + 12
    since = "%04d-%02d" % (y, m)
    done = picked_urls()
    lines = ["# 見出し候補 %s" % today, "",
             "国会図書館: %s以降に索引された記事 / Fujisan: 最新号の目次。picks/ 掲載済みの国会図書館記事は除外。" % since, ""]
    failed = []
    if a.only != "fujisan":
        for src in srcs["ndl"]:
            log("NDL", src["name"])
            items = ndl(src, since)
            if items is None:
                failed.append("国会図書館:" + src["name"]); continue
            items = [x for x in items if x["url"] not in done]
            lines += ["## %s [%s] 国会図書館 %d本" % (src["name"], src["genre"], len(items)), ""]
            for x in items:
                sec = "【%s】" % x["section"] if x["section"] else ""
                lines.append("- %s%s ｜%s ｜%s" % (sec, x["title"], x["issue"], x["url"]))
            lines.append("")
    if a.only != "ndl":
        for src in srcs["fujisan"]:
            log("Fujisan", src["name"])
            items, issue, page = fujisan(src)
            if items is None:
                failed.append("Fujisan:" + src["name"]); continue
            lines += ["## %s [%s] Fujisan最新号 %s" % (src["name"], src["genre"], issue), "号ページ: " + page, ""]
            for x in items:
                if "raw" in x:
                    lines.append("> " + x["raw"]); continue
                sec = "【%s】" % x["section"] if x["section"] else ""
                lines.append("- %s%s" % (sec, x["title"][:120]))
            if not items:
                lines.append("- (目次の掲載なし)")
            lines.append("")
    if failed:
        lines += ["## 取得失敗", ""] + ["- " + f for f in failed]
    out = a.out or os.path.join(ROOT, "candidates", "%s.md" % today)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("wrote", out, "/ 失敗:", ", ".join(failed) or "なし")
    return 1 if failed and len(failed) == len(srcs["ndl"]) + len(srcs["fujisan"]) else 0


if __name__ == "__main__":
    sys.exit(main())
