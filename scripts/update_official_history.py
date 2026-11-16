"""Archive the actual release notes published by iKuai."""

import argparse
import hashlib
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from official import official4_text, sections
from catalog_format import official_valid

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = 'official-history.md'
PAGES = {
    '免费版': 'https://www.ikuai8.com/index.php?option=com_content&view=article&id=331',
    '企业版': 'https://www.ikuai8.com/index.php?option=com_content&view=article&id=447',
}
DOWNLOAD = 'https://www.ikuai8.com/component/download'
VERSION = re.compile(r'(?<!\d)([34]\.\d+\.\d+)(?!\d)')
BUILD = re.compile(r'Build\s*(\d{12})(?!\d)', re.I)
DATE = r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'
CARD = re.compile(
    r'<div class="logs_list">\s*<div class="logs_head[^"]*">\s*'
    r'<div class="fl">(.*?)</div>\s*<div class="fr">(.*?)</div>\s*</div>\s*'
    r'<div class="log_data">(.*?)</div>\s*</div>', re.I | re.S
)
CARD_START = re.compile(r'<div class="logs_list">', re.I)
SECTION = re.compile(r'<h4\b[^>]*>(.*?)</h4>|<pre\b[^>]*>(.*?)</pre>', re.I | re.S)
LATEST = re.compile(r'版本号[：:]\s*(iKuai8_3\.[\w.]+)</span></li>\s*'
                    r'<li[^>]*><span>更新时间[：:]\s*(' + DATE + r')', re.I)
ITEM = re.compile(r'^<!-- ikuai-log:(免费版|企业版):([a-f0-9]{64}) -->\n', re.M)
END = '<!-- /ikuai-log -->\n'
HEADING = (
    '# 爱快官方历史更新日志\n\n'
    f'来源：[免费版历史日志]({PAGES["免费版"]})、[企业版历史日志]({PAGES["企业版"]})、'
    f'[官网下载页]({DOWNLOAD})及官方 4.x 版本接口。仅收录官方提供了更新正文的版本。\n\n'
    '版本名称、发布时间和 Build 以来源为准；官网未给出的字段省略。\n'
)


def plain(text):
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.I)
    return html.unescape(re.sub(r'<[^>]+>', '', text)).strip()


def body_parts(fragment, pattern=SECTION):
    parts = []
    label = ''
    for heading, body in pattern.findall(fragment):
        if heading:
            label = plain(heading)
        elif body := plain(body):
            parts.append((label, body))
            label = ''
    return tuple(parts)


def parse_history(page):
    rows = []
    cards = CARD.findall(page)
    if not cards or len(cards) != len(CARD_START.findall(page)):
        raise ValueError('官网历史日志结构不完整')
    for raw_title, raw_date, raw_body in cards:
        title, date = plain(raw_title), plain(raw_date)
        parts = body_parts(raw_body)
        if not VERSION.search(title) or not re.fullmatch(DATE, date) or not parts:
            raise ValueError('官网历史日志缺少版本、时间或正文')
        rows.append((title, date, parts))
    return rows


def parse_download(page):
    for title, date in LATEST.findall(page):
        edition = '企业版' if '_Enterprise_' in title else '免费版'
        modal = 'company_log' if edition == '企业版' else 'new_log'
        match = re.search(r'<div\b[^>]*id="' + modal + r'"[^>]*>(.*?)</pre>\s*</div>\s*</div>\s*</div>',
                          page, re.I | re.S)
        if match:
            fragment = match[1] + '</pre>'
            pattern = re.compile(r'<div class="log_head">(.*?)</div>|<pre\b[^>]*>(.*?)</pre>', re.S)
            if parts := body_parts(fragment, pattern):
                yield edition, title, date, parts


def parse_4x(text, model):
    for section, fields in sections(text):
        if re.sub(r'_(?:BETA|PREVIEW|PRE)$', '', section, flags=re.I) != model:
            continue
        name = fields.get('firmware_x64') or fields.get('firmware', '')
        if not official_valid(name, model):
            continue
        version, build = VERSION.search(name), BUILD.search(name)
        body = re.sub(r'\\+n', '\n', fields.get('update_content', '')).strip()
        if version and build and version[1] == fields.get('system_ver') and body:
            kind = '企业版' if model == 'X86ENT' else '免费版'
            title = f'爱快 {version[1]} Build{build[1]}'
            if section != model:
                title += f'（{section.split("_")[-1]}）'
            yield kind, title, '', (('', body),)


def escape(text):
    return html.escape(text, quote=False).replace('\\', '&#92;').replace('`', '&#96;')


def make_block(edition, title, date, parts, source):
    key = edition, hashlib.sha256((title + '\0' + date).encode('utf-8')).hexdigest()
    provenance = f'[来源]({source})' if source else '来源：官方 4.x 版本接口'
    metadata = (f'官网发布：{date} · ' if date else '') + provenance
    lines = [f'### {escape(title)}', '', metadata, '']
    for label, body in parts:
        if label:
            lines += [f'**{escape(label)}**', '']
        content_lines = body.splitlines()
        lines += ['> ' + escape(line.rstrip()) + ('<br>' if i < len(content_lines)-1 else '')
                  if line.strip() else '>' for i, line in enumerate(content_lines)]
        lines.append('')
    return key, '\n'.join(lines).rstrip() + '\n'


def existing(text):
    result = {}
    markers = list(ITEM.finditer(text))
    for m in markers:
        key = tuple(m.groups())
        block, end, _ = text[m.end():].partition(END)
        if (not end or key in result or '<!-- ikuai-log:' in block or not block.startswith('### ')
                or not any(row.startswith('> ') for row in block.splitlines())):
            raise ValueError('现有日志格式错误或缺少正文')
        result[key] = block
    return result


def render(entries):
    text = HEADING
    for edition in PAGES:
        text += f'\n## {edition}\n\n'
        blocks = [(key, block) for key, block in entries.items() if key[0] == edition]
        def sort_order(it):
            block = it[1]
            v = VERSION.search(block.splitlines()[0])
            return (tuple(map(int, v[1].split('.'))), block) if v else ((), block)
        for (kind, key), block in sorted(blocks, key=sort_order, reverse=True):
            text += f'<!-- ikuai-log:{kind}:{key} -->\n{block}{END}\n'
    return text.rstrip() + '\n'


def remove_duplicate_channels(entries):
    by_release = {(edition, block.splitlines()[0]): block.partition('\n')[2]
                  for (edition, _), block in entries.items()}
    for key, block in list(entries.items()):
        title, _, body = block.partition('\n')
        stable = re.sub(r'（(?:BETA|PREVIEW|PRE)）$', '', title)
        if title != stable and by_release.get((key[0], stable)) == body:
            del entries[key]


def fetch(url):
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html'})
    with urllib.request.urlopen(req, timeout=15) as rsp:
        payload = rsp.read(2 * 1024**2 + 1)
    if len(payload) > 2 * 1024**2:
        raise ValueError('官网页面超出大小限制')
    return payload.decode('utf-8-sig')


def update(root=ROOT, fetcher=fetch, gateway=''):
    path = root / OUTPUT
    original = path.read_text(encoding='utf-8') if path.exists() else ''
    entries = existing(original)
    # One-time migration: require both official archives before replacing the old metadata table.
    initial = not entries
    with ThreadPoolExecutor(max_workers=5) as pool:
        history = {edition:pool.submit(fetcher, url) for edition, url in PAGES.items()}
        latest = pool.submit(fetcher, DOWNLOAD)
        manifests = {m:pool.submit(official4_text, m, gateway) for m in ('X86', 'X86ENT')} if gateway else {}
        for edition, job in history.items():
            try:
                rows = parse_history(job.result())
            except (OSError, ValueError) as exc:
                if initial:
                    raise
                print(f'::warning::{edition}历史日志未更新：{type(exc).__name__}')
                continue
            for title, date, parts in rows:
                key, block = make_block(edition, title, date, parts, PAGES[edition])
                entries[key] = block
            print(f'{edition}官网历史日志：{len(rows)} 条')
        try:
            for edition, title, date, parts in parse_download(latest.result()):
                key, block = make_block(edition, title, date, parts, DOWNLOAD)
                entries.setdefault(key, block)
        except (OSError, ValueError) as exc:
            print(f'::warning::官网下载页未更新：{type(exc).__name__}')
        for model, job in manifests.items():
            try:
                for edition, title, date, parts in parse_4x(job.result(), model):
                    key, block = make_block(edition, title, date, parts, None)
                    entries[key] = block
            except (OSError, ValueError) as exc:
                print(f'::warning::{model} 4.x 更新说明未更新：{type(exc).__name__}')
    remove_duplicate_channels(entries)
    content = render(entries)
    if existing(content) != entries:
        raise ValueError('生成的更新日志未通过校验')
    if content != original:
        tmp = path.with_suffix('.md.tmp')
        tmp.write_bytes(content.encode('utf-8'))
        tmp.replace(path)
    print(f'含正文的更新日志：{len(entries)} 条。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        content = (ROOT / OUTPUT).read_text(encoding='utf-8')
        records = existing(content)
        if not records or render(records) != content:
            raise ValueError('历史更新日志格式错误')
        print(f'历史更新日志校验通过：{len(records)} 条。')
    else:
        update(gateway=os.environ.get('IKUAI_INDEX_GATEWAY', ''))


if __name__ == '__main__':
    main()
