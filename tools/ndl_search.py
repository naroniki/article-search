#!/usr/bin/env python3
"""国立国会図書館サーチ OpenSearch API で資料を検索する(標準ライブラリのみ)。
使い方: python3 tools/ndl_search.py "キーワード" [--cnt 20] [--from 2015] [--until 2025]
"""
import argparse
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ENDPOINT = "https://ndlsearch.ndl.go.jp/api/opensearch"
NS = {"dc": "http://purl.org/dc/elements/1.1/", "dcterms": "http://purl.org/dc/terms/"}


def search(keyword, cnt=10, year_from=None, year_until=None):
    params = {"any": keyword, "cnt": str(cnt)}
    if year_from:
        params["from"] = year_from
    if year_until:
        params["until"] = year_until
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "neta-lab/0.1"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return parse(res.read()), url


def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        def text(tag, ns=None):
            el = item.find(tag, ns) if ns else item.find(tag)
            return el.text.strip() if el is not None and el.text else ""
        creators = [c.text.strip() for c in item.findall("dc:creator", NS) if c.text]
        items.append({
            "title": text("title"),
            "creator": " / ".join(creators),
            "publisher": text("dc:publisher", NS),
            "date": text("dcterms:issued", NS) or text("pubDate"),
            "link": text("link"),
        })
    return items


def main():
    p = argparse.ArgumentParser()
    p.add_argument("keyword")
    p.add_argument("--cnt", type=int, default=10)
    p.add_argument("--from", dest="year_from")
    p.add_argument("--until", dest="year_until")
    a = p.parse_args()
    try:
        items, url = search(a.keyword, a.cnt, a.year_from, a.year_until)
    except Exception as e:
        print(f"ERROR: 国会図書館サーチに接続できませんでした: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"# 検索: {a.keyword} ({len(items)}件)\n# {url}\n")
    for i, it in enumerate(items, 1):
        print(f"{i}. {it['title']}")
        meta = " | ".join(x for x in (it["creator"], it["publisher"], it["date"]) if x)
        if meta:
            print(f"   {meta}")
        print(f"   {it['link']}")


if __name__ == "__main__":
    main()
