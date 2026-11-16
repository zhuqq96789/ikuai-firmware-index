"""Append releases from the iKuai website and the cached official API catalog."""

import argparse
import html
import re
import urllib.request
from pathlib import Path

from catalog_format import catalog_decode

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = "official-history.md"
PAGES = {
    "免费版": "https://www.ikuai8.com/index.php?option=com_content&view=article&id=331",
    "企业版": "https://www.ikuai8.com/index.php?option=com_content&view=article&id=447",
}
VERSION = re.compile(r"(?<!\d)([34]\.\d+\.\d+)(?!\d)")
BUILD = re.compile(r"Build\s*(\d{12})(?!\d)", re.I)
LOG_HEAD = re.compile(
    r'<div\b[^>]*class=["\'][^"\']*\blogs_head\b[^"\']*["\'][^>]*>\s*'
    r'<div\b[^>]*>(.*?)</div>\s*<div\b[^>]*>(.*?)</div>', re.I | re.S
)
TABLE = "| 来源 | 类别 / 型号 | 版本 | Build | 官网发布时间 | 官网日志标题 |"
HEADING = """# 爱快官方历史版本

收录爱快官网发布日志和官方固件目录中的 3.x、4.x 版本。每天检查并追加新记录，旧记录保留。

- 官网日志：[免费版](""" + PAGES["免费版"] + """)、[企业版](""" + PAGES["企业版"] + """)。缺少 Build 时显示「—」。
- 官方固件目录取自 [catalog.json](data/catalog.json) 的官方条目；同类别、型号、版本和 Build 的多个架构或文件格式合为一行。
- 官网发布时间和 Build 分列。日志记录不代表固件仍可下载。

""" + TABLE + "\n| --- | --- | --- | --- | --- | --- |\n"


def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return " ".join(text.split())


def cell(text):
    return html.escape(text, quote=False).replace("|", "&#124;").replace("`", "&#96;")


def fetch(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = response.read(2 * 1024**2 + 1)
    if len(payload) > 2 * 1024**2:
        raise ValueError("unexpected website response size")
    return payload.decode("utf-8-sig")


def parse_log(page, edition):
    rows = set()
    for raw_title, raw_date in LOG_HEAD.findall(page):
        title, published = clean(raw_title), clean(raw_date)
        version = VERSION.search(title)
        if not version:
            continue
        build = BUILD.search(title)
        rows.add(("官网日志", edition, version[1], build[1] if build else "—",
                  published or "—", title))
    if not rows:
        raise ValueError("no release titles in page")
    return rows


def api_rows(path):
    _, _, official = catalog_decode(path.read_bytes())
    rows = set()
    for name, model in official:
        version, build = VERSION.search(name), BUILD.search(name)
        if version and build:
            label = {"X86": "x86 免费版", "X86ENT": "x86 企业版"}.get(model, model)
            rows.add(("官方固件目录", label, version[1], build[1], "—", "—"))
    return rows


def read_rows(text):
    _, marker, block = text.partition(TABLE + "\n| --- | --- | --- | --- | --- | --- |\n")
    if not marker:
        raise ValueError("existing Markdown table header does not match")
    rows = []
    for line in block.splitlines():
        if not line.strip():
            continue
        if not line.startswith("| ") or not line.endswith(" |"):
            raise ValueError("invalid existing Markdown row")
        row = tuple(html.unescape(part) for part in line[2:-2].split(" | "))
        if (len(row) != 6 or row[0] not in ("官网日志", "官方固件目录")
                or not VERSION.fullmatch(row[2]) or not re.fullmatch(r"\d{12}|—", row[3])):
            raise ValueError("invalid existing version record")
        rows.append(row)
    if not rows or len(set(rows)) != len(rows):
        raise ValueError("empty or duplicate version records")
    return rows


def update(root=ROOT, fetcher=fetch):
    target = root / OUTPUT
    original = target.read_text(encoding="utf-8") if target.exists() else ""
    prior = set(read_rows(original)) if original else set()
    incoming = set()
    for edition, url in PAGES.items():
        try:
            rows = parse_log(fetcher(url), edition)
        except (OSError, ValueError) as exc:
            print(f"::warning::{edition}官网日志未更新（{type(exc).__name__}），旧记录保留。")
            continue
        incoming.update(rows)
        print(f"{edition}官网日志：{len(rows)} 条")
    rows = api_rows(root / "data/catalog.json")
    incoming.update(rows)
    print(f"官方固件目录：{len(rows)} 条（按型号和 Build 合并）")
    if not incoming:
        raise RuntimeError("没有读到官方版本；保留现有文件。")
    additions = sorted(incoming - prior, key=lambda r: (
        r[0] == "官网日志", r[1], tuple(map(int, r[2].split("."))), r[3], r[4], r[5]
    ), reverse=True)
    print(f"追加 {len(additions)} 条，原有 {len(prior)} 条。")
    if not additions:
        return
    content = (original or HEADING).rstrip("\n") + "\n" + "".join(
        "| " + " | ".join(map(cell, row)) + " |\n" for row in additions
    )
    read_rows(content)
    temporary = target.with_suffix(".md.tmp")
    temporary.write_bytes(content.encode("utf-8"))
    temporary.replace(target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        rows = read_rows((ROOT / OUTPUT).read_text(encoding="utf-8"))
        print(f"历史版本 Markdown 校验通过：{len(rows)} 条。")
    else:
        update()


if __name__ == "__main__":
    main()
