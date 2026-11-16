"""Archive the actual release notes published by iKuai."""

import hashlib
import html
import json
from collections import defaultdict
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
SOURCES = re.compile(r'^<!-- ikuai-sources:(.*) -->\n', re.M)
GROUP_END = '<!-- /ikuai-sources -->\n'
BUILD_TOKEN = '{build}'
HEADING = (
    '# 爱快官方历史更新日志\n\n'
    f'来源：[免费版历史日志]({PAGES["免费版"]})、[企业版历史日志]({PAGES["企业版"]})、'
    f'[官网下载页]({DOWNLOAD})及官方 3.x、4.x 版本接口。仅收录官方提供了更新正文的版本。\n\n'
    '每个 Build 只列一次；相同的更新正文合并，正文有差异时标注适用范围。\n'
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


def legacy_entries(text):
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


def existing(text):
    if not SOURCES.search(text):
        return legacy_entries(text)
    records = {}
    for section in re.split(r'^## ', text, flags=re.M)[1:]:
        heading = section.splitlines()[0]
        build = BUILD.search(heading)
        for match in SOURCES.finditer(section):
            tail = section[match.end():]
            _, sep, notes = tail.partition('\n\n')
            body, end, _ = notes.partition(GROUP_END)
            if not sep or not end or not any(x.startswith('> ') for x in body.splitlines()):
                raise ValueError('Build 的更新正文不完整')
            for kind, key, title, metadata in json.loads(match[1]):
                identity = kind, key
                if (kind not in GROUPS or not re.fullmatch(r'[0-9a-f]{64}', key)
                        or identity in records or not title.startswith('### ')):
                    raise ValueError('Build 的来源记录无效或重复')
                if build:
                    title = title.replace(BUILD_TOKEN, build[1])
                records[identity] = f'{title}\n\n{metadata}\n\n{body}'
    return records


def release_version(title):
    match = VERSION.search(title)
    return match[1] if match else ''


def applicability(members, versions):
    scopes = set()
    for edition, _, title, _ in members:
        version = release_version(title)
        if edition == '官方设备':
            scope = title[4:].split()[0]
        else:
            scope = edition
        if len(versions)>1:
            scope += f' {version}'
        if channel := re.search(r'（(BETA|PREVIEW|PRE)）$', title):
            scope += f'（{channel[1]}）'
        scopes.add(scope)
    return '、'.join(sorted(scopes))


def render(entries):
    builds = defaultdict(list)
    no_build = []
    for (edition, key), block in entries.items():
        title, metadata, body = block.split('\n\n', 2)
        if match := BUILD.search(title):
            stamp = match[1]
            title = title[:match.start(1)] + BUILD_TOKEN + title[match.end(1):]
            builds[stamp].append((edition, key, title, metadata, body))
        else:
            no_build.append((edition, key, title, metadata, body))
    text = HEADING
    for stamp, members in sorted(builds.items(), reverse=True):
        versions = sorted({release_version(x[2]) for x in members}, key=lambda v: tuple(map(int,v.split('.'))))
        text += f'\n## {" / ".join(versions)} · Build{stamp}\n\n'
        text += render_bodies(members, versions)
    if no_build:
        text += '\n## 未标注 Build 的官网日志\n'
        for record in sorted(no_build, key=lambda x: (
                tuple(map(int,release_version(x[2]).split('.'))), x[3], x[0]), reverse=True):
            edition, _, title, _, _ = record
            text += f'\n### {edition} · {title[4:]}\n\n'
            text += render_bodies([record], [release_version(title)])
    return text.rstrip() + '\n'


def render_bodies(members, versions):
    bodies = defaultdict(list)
    for edition, key, title, metadata, body in members:
        bodies[body].append((edition,key,title,metadata))
    text = ''
    for body, source in sorted(bodies.items(), key=lambda x: sorted(x[1])):
        # The comment stores provenance and stable IDs; each body is stored once.
        encoded = json.dumps(sorted(source), ensure_ascii=False, separators=(',',':'))
        encoded = encoded.replace('<!--', '\\u003c!--').replace('-->', '--\\u003e')
        scope = applicability(source, versions)
        meta = '；'.join(sorted({x[3] for x in source if x[3]}))
        text += f'<!-- ikuai-sources:{encoded} -->\n**适用：** {scope}'
        if meta:
            text += f'  ·  {meta}'
        text += f'\n\n{body}{GROUP_END}\n'
    return text


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
    builds = {m[1] for block in entries.values() if (m := BUILD.search(block.splitlines()[0]))}
    print(f'更新日志：{len(builds)} 个去重后的 Build（{len(entries)} 条来源记录）')
    return content


def validate(content):
    records = existing(content)
    if not records or render(records) != content:
        raise ValueError('历史更新日志格式错误')
    builds = {m[1] for block in records.values() if (m := BUILD.search(block.splitlines()[0]))}
    return len(builds)
