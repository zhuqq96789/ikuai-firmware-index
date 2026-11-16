import argparse,datetime as dt,json,os,re
from pathlib import Path
from index_format import decode
from catalog_format import catalog_decode,catalog_encode,device_model
from official import collect,extract,ALLOWED_4_MODELS
ROOT=Path(__file__).resolve().parents[1]
CATALOG=Path('data/catalog.json')
PC_LISTS={
 ('3','free'):'version_list.txt',('3','enterprise'):'version_enterprise_list.txt',
 ('4','free'):'version_4_list.txt',('4','enterprise'):'version_4_enterprise_list.txt',
}
def day():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
def notes_only(base):
    path=base/'data/release-notes-only.json'
    if not path.is_file():
        return []
    records=json.loads(path.read_bytes())['records']
    return [(r['list'],r['version']) for r in records]

def version_lines(archive,official,documented=()):
    names={e['filename'] for e in archive}|{name for name,_ in official}
    lists={Path(p):set() for p in PC_LISTS.values()}
    for name in names:
        v=re.search(r'_(\d+\.\d+\.\d+)_',name)
        b=re.search(r'_Buil(?:d)?(\d{12})\.',name,re.I)
        if not v or not b:continue
        version=v[1]
        model=device_model(name)
        path=Path('devices')/(model+'.txt') if model else Path(PC_LISTS[(version[0],'enterprise' if '_enterprise_' in name.lower() else 'free')])
        lists.setdefault(path,set()).add((tuple(map(int,version.split('.'))),b[1]))
    for filename,build in documented:
        match=re.fullmatch(r'([34]\.\d+\.\d+)_Build(\d{12})',build)
        if filename not in PC_LISTS.values() or not match:
            raise ValueError('Malformed release-note-only record')
        lists[Path(filename)].add((tuple(map(int,match[1].split('.'))),match[2]))
    return {p:''.join('.'.join(map(str,v))+'_Build'+b+'\n' for v,b in sorted(rows,reverse=True)).encode()
            for p,rows in lists.items()}

def write(path,data):
    if path.is_file() and path.read_bytes()==data:return
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_bytes(data)
    temp.replace(path)

def seed(base,legacy_dir):
    _,archive=decode((base/'history.txt').read_bytes())
    rows=extract((legacy_dir/'ikuai-device-3x.txt').read_text(encoding='utf-8-sig'),'3')
    for model in ('X86','X86ENT',*ALLOWED_4_MODELS):
        path=legacy_dir/('mirror-manifest-'+model+'.data' if model.startswith('X86') else f'device4-manifest-{model}.ini')
        if path.exists():
            rows.update(extract(path.read_text(encoding='utf-8-sig'),'4',model))
    write(base/CATALOG,catalog_encode(day(),archive,rows))
    for p,content in version_lines(archive,rows,notes_only(base)).items():write(base/p,content)

def update(base,fetch=collect):
    old_date,archive,official=catalog_decode((base/CATALOG).read_bytes())
    known3={model for name,model in official if '_3.' in name and device_model(name)}
    known4={model for name,model in official if '_4.' in name and device_model(name)}
    rows,failed=fetch(os.environ.get('IKUAI_INDEX_GATEWAY',''),known3,known4)
    if not rows:
        raise RuntimeError('All official queries failed; existing index preserved.')
    union=official|rows
    print('New official files:',len(union)-len(official))
    write(base/CATALOG,catalog_encode(day() if union!=official else old_date,archive,union))
    for p,content in version_lines(archive,union,notes_only(base)).items():write(base/p,content)

def check(base):
    _,archive,official=catalog_decode((base/CATALOG).read_bytes())
    expected=version_lines(archive,official,notes_only(base))
    for p,data in expected.items():
        if (base/p).read_bytes()!=data:raise ValueError('Inconsistent list: '+str(p))
    print(f'{len(expected)} version files; {len(archive)} archive files; {len(official)} official files')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seed',type=Path)
    parser.add_argument('--check',action='store_true')
    opt=parser.parse_args()
    if opt.seed:seed(ROOT,opt.seed)
    elif not opt.check:update(ROOT)
    check(ROOT)

if __name__=='__main__': main()
