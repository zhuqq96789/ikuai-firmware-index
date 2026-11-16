import collections
import concurrent.futures
import datetime as dt
import html
import json
import re
import time
import urllib.error
import urllib.parse as url
import urllib.request as net
from pathlib import Path

from index_format import DEVICE, valid_filename
import os

HERE=Path(__file__).resolve().parent
LUC='LucienShui/ikuai-firmware'
LOVE='LOVECHEN/ikuai-release'
SHINI='shiniuniu/ikuai-firmware-public'
PROJECTS=(LUC,LOVE,SHINI)
GH='https://github.com/'
RAW='https://raw.githubusercontent.com/'
INDEX=('version_enterprise_list.txt','version_list.txt','version_4_list.txt')
SHA=re.compile(r'[a-f0-9]{64}')
TAG=re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,149}')
ASSET=re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,180}')
ALIAS=re.compile(r'(?P<model>[A-Za-z0-9-]+)-(?P<version>[34]\.\d+\.\d+)\.bin')
MAX_BYTES=6*1024**2

def supported(name):
    return valid_filename(name)

def release_page(project, tag):
    return f'{GH}{project}/releases/tag/{tag}'

def asset_url(project,tag,asset):
    if project not in (LOVE,SHINI) or not isinstance(tag,str) or not TAG.fullmatch(tag):
        raise ValueError('Release 标签无效。')
    if not isinstance(asset,str) or not ASSET.fullmatch(asset):
        raise ValueError('Release 资产名无效。')
    return f'{GH}{project}/releases/download/{tag}/{asset}'

class PublicRedirect(net.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        u=url.urlsplit(newurl)
        if u.scheme!='https' or u.username is not None:
            raise ValueError('Insecure redirect')
        if u.netloc.lower() not in ('github.com','api.github.com','raw.githubusercontent.com',
            'release-assets.githubusercontent.com','objects.githubusercontent.com',
            'github-releases.githubusercontent.com','github-cloud.s3.amazonaws.com'):
            raise ValueError('GitHub 下载跳到了未识别的主机。')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(urltext,limit=MAX_BYTES):
    req=net.Request(urltext,headers={'User-Agent':'iKuaiToolbox/2.0','Accept-Encoding':'identity'})
    if url.urlsplit(urltext).netloc=='api.github.com' and os.environ.get('GITHUB_TOKEN'):
        req.add_unredirected_header('Authorization','Bearer '+os.environ['GITHUB_TOKEN'])
    with net.build_opener(PublicRedirect()).open(req,timeout=15) as rsp:
        chunks=[]
        size=0
        deadline=time.monotonic()+65
        while True:
            part=rsp.read1(65536)
            if not part:break
            size+=len(part)
            if size>limit or time.monotonic()>deadline:
                raise ValueError('在线索引超过下载限制。')
            chunks.append(part)
        return b''.join(chunks)

def source_row(name,project,src,href='',sha=''):
    return dict(filename=name,project=project,source=src,url=href,sha256=sha)

def lucien(blobs):
    rows=[]
    for name in INDEX:
        data=blobs[name].decode('utf-8-sig')
        if not data.strip():raise ValueError('LucienShui 索引为空')
        ent=name==INDEX[0]
        for line in data.splitlines():
            match=re.fullmatch(r'([34]\.\d+\.\d+)_(Build\d{12})',line.strip())
            if not match:continue
            for arch in ('64','32'):
                for fmt in (('bin',) if ent else ('bin','iso')):
                    firm=f"iKuai8_x{arch}_{match[1]}_{'Enterprise_' if ent else ''}{match[2]}.{fmt}"
                    rows.append(source_row(firm,LUC,f'{GH}{LUC}/blob/main/{name}'))
    return rows

def love_catalog(catalog,reports):
    data=json.loads(catalog)['files']
    rep={r['tag']:r for r in json.loads(reports)}
    sizes=collections.Counter(f['tag'] for f in data)
    bad={}
    for tag,total in sizes.items():
        r=rep.get(tag) or {}
        failures=r.get('failures') or []
        if total-len(failures)==r.get('archived') and all(isinstance(f.get('id'),str) for f in failures):
            bad[tag]={x['id'] for x in failures}
    if not bad:
        raise ValueError('LOVECHEN 候选目录与归档报告不匹配。')
    result=[]
    for f in data:
        name=f.get('filename')
        tag=f.get('tag')
        if tag not in bad or f['id'] in bad[tag] or not supported(name):
            continue
        a=f.get('asset_name') or name
        try: href=asset_url(LOVE,tag,a)
        except ValueError: continue
        result.append(source_row(name,LOVE,release_page(LOVE,tag),href))
    return result

def digest(val):
    s=val.removeprefix('sha256:').lower() if isinstance(val,str) else ''
    return s if SHA.fullmatch(s) else ''

def shini_catalog(releases, loader=fetch, existing_aliases=None):
    rows=[]
    for r in releases:
        tag=r.get('tag_name','')
        if not TAG.fullmatch(tag) or r.get('draft'):continue
        assets={a.get('name'):a for a in r.get('assets',[]) if a.get('state','uploaded')=='uploaded'}
        for name,a in assets.items():
            if not isinstance(name,str) or not name.lower().endswith(('.bin','.iso')) or not ASSET.fullmatch(name):
                continue
            sha=digest(a.get('digest'))
            canonical=name
            if not supported(name):
                al=ALIAS.fullmatch(name)
                manifest=name[:-4]+'.manifest.json'
                if not al or manifest not in assets:
                    continue
                alias_url=asset_url(SHINI,tag,name)
                prior=(existing_aliases or {}).get(alias_url)
                try:
                    if prior and sha and sha==prior['sha256']:
                        canonical=prior['filename']
                    else:
                        meta=json.loads(loader(asset_url(SHINI,tag,manifest),65536))
                        other=digest(meta.get('file_sha256'))
                        canonical=meta.get('firmware_file','')
                        m=DEVICE.fullmatch(canonical)
                        if (not m or m['version']!=al['version'] or meta.get('model')!=al['model']
                            or not m['folder'].endswith('-'+al['model']) or (sha and sha!=other)):
                            continue
                        sha=sha or other
                except Exception:
                    continue
            rows.append(source_row(canonical,SHINI,release_page(SHINI,tag),asset_url(SHINI,tag,name),sha))
    return rows

def list_shini(loader):
    base=f'https://api.github.com/repos/{SHINI}/releases?per_page=100'
    try:
        releases=[]
        for page in range(1,11):
            lst=json.loads(loader(base+(f'&page={page}' if page>1 else ''),MAX_BYTES))
            if not isinstance(lst,list):
                raise ValueError('Releases 响应不正确。')
            releases.extend(lst)
            if len(lst)<100:
                return releases
        raise ValueError('Releases 超出分页上限。')
    except (OSError, ValueError, TypeError):
        base=GH+SHINI+'/releases'
        tags=set()
        for page in range(1,11):
            pageurl=base if page==1 else base+f'?page={page}'
            text=loader(pageurl,2*1024**2).decode('utf-8','replace')
            tags.update(re.findall(r'/releases/expanded_assets/([A-Za-z0-9._-]+)',text))
            if not re.search(r'rel="next"[^>]+href="[^"]*\?page='+str(page+1)+r'"',text):
                break
        if not tags or len(tags)>40:
            raise ValueError('未找到可读取的 Releases 资产目录。')
        def html_assets(tag):
            text=loader(base+'/expanded_assets/'+tag,2*1024**2).decode('utf-8','replace')
            pattern=r'/'+re.escape(SHINI)+r'/releases/download/'+re.escape(tag)+r'/([^"<>\s]+)'
            names={url.unquote(html.unescape(p)) for p in re.findall(pattern,text)}
            return {'tag_name':tag,'assets':[{'name':n} for n in sorted(names)]}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            return list(ex.map(html_assets,sorted(tags)))

def online(project,loader=fetch,builtin=()):
    if project==LUC:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            return lucien(dict(zip(INDEX,ex.map(lambda f:loader(RAW+LUC+'/main/'+f,256*1024),INDEX))))
    if project==LOVE:
        base=GH+LOVE+'/releases/download/mirror-index/'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            first=ex.submit(loader,base+'catalog.json',MAX_BYTES)
            second=ex.submit(loader,base+'reports.json',MAX_BYTES)
            return love_catalog(first.result(),second.result())
    aliases={r['url']:r for r in builtin if r['url'] and r['sha256']}
    return shini_catalog(list_shini(loader),loader,aliases)

def combine(rows):
    key={}
    for r in rows:
        if not supported(r['filename']) or r['project'] not in PROJECTS: continue
        k=r['filename'].casefold()
        prior=key.setdefault(k,dict(filename=r['filename'],refs=[]))
        if not any(p['project']==r['project'] and p['url']==r['url'] for p in prior['refs']):
            prior['refs'].append({p:r[p] for p in ('project','source','url','sha256')})
    return list(key.values())

