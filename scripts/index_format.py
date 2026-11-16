import json
import re
from datetime import date
from urllib.parse import urlsplit

PROJECTS=('LucienShui/ikuai-firmware','LOVECHEN/ikuai-release','shiniuniu/ikuai-firmware-public',
          'iKuaiPatch/firmware_archive','bikefly/ikuaifw')
LUC,LOVE,SHINI,PATCH,BIKE=PROJECTS
RAW_PROJECTS=(PATCH,BIKE)
DEVICE=re.compile(r'(?P<folder>IK-[A-Za-z0-9-]+)_sysupgrade_(?P<version>[34]\.\d+\.\d+)_Build\d{12}\.bin')
PC=re.compile(r'iKuai8_x(?:32|64)_[34]\.\d+\.\d+_(?:beta_)?(?:Enterprise_)?(?:beta_)?Buil(?:d)?\d{11,12}\.(?:bin|iso)',re.I)
SHA=re.compile(r'[a-f0-9]{64}')
SLUG=r'[A-Za-z0-9][A-Za-z0-9._-]{0,180}'
GIT_PATH=rf'[a-f0-9]{{40}}/(?:{SLUG}/)*{SLUG}'
MAGIC='# ikuai-history-tsv-v1'

def valid_filename(name):
    return isinstance(name,str) and bool(PC.fullmatch(name) or DEVICE.fullmatch(name))

def ref_valid(ref):
    if not isinstance(ref,dict) or ref.get('project') not in PROJECTS:
        return False
    p=ref['project']
    src,uri,sha=(ref.get(k,'') for k in ('source','url','sha256'))
    if not all(isinstance(x,str) and x.isascii() and len(x)<1000 and not re.search(r'\s',x) for x in (src,uri,sha)):
        return False
    if sha and not SHA.fullmatch(sha):
        return False
    base='https://github.com/'+p
    if p==LUC:
        return uri=='' and re.fullmatch(re.escape(base)+r'/blob/main/version_(?:list|enterprise_list|4_list)\.txt',src) is not None
    if p in RAW_PROJECTS and (blob:=re.fullmatch(re.escape(base+'/blob/')+f'({GIT_PATH})',src)):
        return uri=='https://raw.githubusercontent.com/'+p+'/'+blob[1]
    tag=re.fullmatch(re.escape(base)+r'/releases/tag/('+SLUG+r')',src)
    if not tag:
        return False
    return re.fullmatch(re.escape(base+'/releases/download/'+tag[1]+'/')+SLUG,uri) is not None

def normalize(entries):
    seen={}
    for item in entries:
        name=item.get('filename')
        if not valid_filename(name):
            continue
        v=seen.setdefault(name.casefold(),{'filename':name,'refs':{}})
        for ref in item.get('refs',[]):
            if not ref_valid(ref):
                continue
            key=(ref['project'],ref['url'] or ref['source'])
            data={k:ref.get(k,'') for k in ('project','source','url','sha256')}
            if key not in v['refs'] or not v['refs'][key]['sha256']:
                v['refs'][key]=data
    return [{'filename':v['filename'],'refs':sorted(v['refs'].values(),key=lambda r:(PROJECTS.index(r['project']),r['url'],r['source']))}
            for _,v in sorted(seen.items()) if v['refs']]

def encode(entries,updated):
    date.fromisoformat(updated)
    entries=normalize(entries)
    if not entries:
        raise ValueError('历史索引为空。')
    head=[MAGIC,'# updated='+updated,'# filename\trefs (project, index_or_tag, asset_override, sha256)']
    def compact(ref,name):
        project=ref['project']
        kind=PROJECTS.index(project)
        if project in RAW_PROJECTS and '/blob/' in ref['source']:
            commit,path=ref['source'].split('/blob/',1)[1].split('/',1)
            item=[kind,'git:'+commit,path]
            return item+[ref['sha256']] if ref['sha256'] else item
        item=[kind,ref['source'].rsplit('/',1)[-1]]
        asset=ref['url'].rsplit('/',1)[-1] if ref['url'] else ''
        override=asset if asset and asset!=name else ''
        if override or ref['sha256']:
            item.append(override)
        if ref['sha256']:
            item.append(ref['sha256'])
        return item
    return '\n'.join(head+[e['filename']+'\t'+json.dumps([compact(r,e['filename']) for r in e['refs']],
        ensure_ascii=False,separators=(',',':')) for e in entries])+'\n'

def expand(ref,name):
    if (not isinstance(ref,list) or not 2<=len(ref)<=4 or type(ref[0]) is not int
        or not 0<=ref[0]<len(PROJECTS) or not all(isinstance(x,str) for x in ref[1:])):
        raise ValueError('来源编码无效。')
    p,target=PROJECTS[ref[0]],ref[1]
    base='https://github.com/'+p
    asset=(ref[2] if len(ref)>2 else '') or name
    sha=ref[3] if len(ref)>3 else ''
    if p in RAW_PROJECTS and target.startswith('git:'):
        locator=target[4:]+'/'+asset
        return {'project':p,'source':base+'/blob/'+locator,
                'url':'https://raw.githubusercontent.com/'+p+'/'+locator,'sha256':sha}
    return {'project':p,
            'source':base+('/blob/main/' if p==LUC else '/releases/tag/')+target,
            'url':'' if p==LUC else base+'/releases/download/'+target+'/'+asset,
            'sha256':sha}

def decode(raw):
    lines=raw.decode('utf-8-sig').splitlines()
    if not lines or lines[0]!=MAGIC:
        raise ValueError('历史索引格式不兼容。')
    updated=next((l.partition('=')[2] for l in lines[:8] if l.startswith('# updated=')),'')
    date.fromisoformat(updated)
    entries=[]
    for line in lines[1:]:
        if not line or line.startswith('#'):
            continue
        name,tab,record=line.partition('\t')
        refs=json.loads(record) if tab else None
        if not valid_filename(name) or not isinstance(refs,list) or not refs:
            raise ValueError('历史索引包含无效的文件名或来源。')
        refs=[expand(ref,name) for ref in refs]
        if not all(ref_valid(r) for r in refs):
            raise ValueError('历史索引包含无效的文件名或来源。')
        entries.append({'filename':name,'refs':refs})
    result=normalize(entries)
    if not result or len(result)!=len(entries):
        raise ValueError('历史索引为空或含有重复文件。')
    return updated,result
