import json,re
from datetime import date
from index_format import decode, encode, normalize, PC, DEVICE
ALLOWED_4_MODELS=('Q3000','Q6000','Q3S','Y3000G-PRO','Y6000G-PRO')

def official_valid(name,model):
    if not isinstance(name,str) or not isinstance(model,str): return False
    if PC.fullmatch(name):
        return model==('X86ENT' if '_enterprise_' in name.lower() else 'X86')
    m=DEVICE.fullmatch(name)
    return (m is not None and re.fullmatch(r'[A-Za-z0-9-]{1,40}',model) is not None
            and m['folder'].rsplit('-',1)[0] and m['folder'].split('-',2)[-1]==model
            and (m['version'].startswith('3.') or model in ALLOWED_4_MODELS))

def device_model(name):
    m=DEVICE.fullmatch(name)
    return m['folder'].split('-',2)[-1] if m else None

def catalog_encode(day,archive,official):
    parts=encode(normalize(archive),day).splitlines()[3:]
    return (json.dumps({'schema':2,'date':day,'archive':[
        [str(row.partition('\t')[0]),json.loads(row.partition('\t')[2])] for row in parts],
        'official':sorted({(name,model) for name,model in official if official_valid(name,model)})},
        ensure_ascii=True,separators=(',',':'))+'\n').encode('ascii')

def catalog_decode(raw):
    j=json.loads(raw)
    if j.get('schema')!=2:
        raise ValueError('历史目录格式不兼容。')
    day=j['date']
    date.fromisoformat(day)
    lines=['# ikuai-history-tsv-v1','# updated='+day,'# filename\trefs']
    for name,refs in j['archive']:
        lines.append(name+'\t'+json.dumps(refs,ensure_ascii=True,separators=(',',':')))
    _,rows=decode(('\n'.join(lines)+'\n').encode('ascii'))
    entries=j['official']
    if not all(isinstance(r,list) and len(r)==2 and official_valid(*r) for r in entries):
        raise ValueError('最近官方目录含有无效条目。')
    unique={(r[0],r[1]) for r in entries}
    if len(unique)!=len(entries):
        raise ValueError('最近官方目录含有重复条目。')
    return day,rows,unique
