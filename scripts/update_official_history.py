"""Archive the actual release notes published by iKuai."""

import hashlib
import html
import re

OUTPUT = 'official-history.md'
PAGES = {
    '免费版': 'https://www.ikuai8.com/index.php?option=com_content&view=article&id=331',
    '企业版': 'https://www.ikuai8.com/index.php?option=com_content&view=article&id=447',
}
DOWNLOAD = 'https://www.ikuai8.com/component/download'
VERSION = re.compile(r'(?<!\d)([34]\.\d+\.\d+)(?!\d)')
BUILD = re.compile(r'Build\s*(\d{12})(?!\d)', re.I)
GROUPS = ('免费版', '企业版', '官方设备')
ITEM = re.compile(r'^<!-- ikuai-log:(免费版|企业版|官方设备):([a-f0-9]{64}) -->\n', re.M)
END = '<!-- /ikuai-log -->\n'
HEADING = (
    '# 爱快官方历史更新日志\n\n'
    f'来源：[免费版历史日志]({PAGES["免费版"]})、[企业版历史日志]({PAGES["企业版"]})、'
    f'[官网下载页]({DOWNLOAD})及官方 3.x、4.x 版本接口。仅收录官方提供了更新正文的版本。\n\n'
    '版本名称、发布时间和 Build 以来源为准；官网未给出的字段省略。\n'
)


def escape(text):
    return html.escape(text, quote=False).replace('\\', '&#92;').replace('`', '&#96;')


def make_block(edition, title, parts, major):
    date = ''
    key = edition, hashlib.sha256((title + '\0' + date).encode('utf-8')).hexdigest()
    metadata = f'来源：官方 {major}.x 版本接口'
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
    for edition in GROUPS:
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


def with_manifest_notes(original, notes):
    entries = existing(original)
    if original and not entries:
        raise ValueError('现有更新日志格式无效，避免覆盖历史正文')
    # Keep the original website text when it already documents the same PC build.
    website = set()
    for (edition, _), block in entries.items():
        if '](https://www.ikuai8.com/' not in block:
            continue
        heading = block.splitlines()[0]
        version, build = VERSION.search(heading), BUILD.search(heading)
        if version and build:
            website.add((edition, version[1], build[1]))
    initial = len(entries)
    for (model, version, build, channel), body in sorted(notes.items()):
        if channel and notes.get((model, version, build, '')) == body:
            continue
        if model == 'X86':
            edition, prefix = '免费版', '爱快'
        elif model == 'X86ENT':
            edition, prefix = '企业版', '爱快'
        else:
            edition, prefix = '官方设备', model
        if not channel and (edition, version, build) in website:
            continue
        title = f'{prefix} {version} Build{build}'
        if channel:
            title += f'（{channel}）'
        key, block = make_block(edition, title, (('', body),), version[0])
        entries[key] = block
    remove_duplicate_channels(entries)
    content = render(entries)
    if existing(content) != entries:
        raise ValueError('生成的更新日志未通过校验')
    print(f'更新日志：{len(entries)} 条（净增 {len(entries)-initial} 条）')
    return content


def validate(content):
    records = existing(content)
    if not records or render(records) != content:
        raise ValueError('历史更新日志格式错误')
    return len(records)
