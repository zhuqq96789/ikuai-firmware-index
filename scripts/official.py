import hashlib,hmac,json,re,secrets,urllib.error,urllib.parse,urllib.request
from concurrent.futures import ThreadPoolExecutor
from catalog_format import ALLOWED_4_MODELS, official_valid
LEGACY='https://download.ikuai8.com/submit3x/Version_all'
API='https://devapi.ikuai8.com/firmware/version-all'
OSS='cloud-dev-fireware.oss-cn-beijing.aliyuncs.com'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):
        raise ValueError('unexpected redirect')

def fetch(uri,headers=None):
    r=urllib.request.Request(uri,headers={'User-Agent':'iKuaiFirmwareIndex/2.2',**(headers or {})})
    with urllib.request.build_opener(NoRedirect()).open(r,timeout=12) as f:
        data=f.read(1024**2+1)
    if len(data)>1024**2: raise ValueError('manifest too large')
    return data

def sections(text):
    model=None
    fields={}
    for line in text.splitlines():
        line=line.strip()
        if m:=re.fullmatch(r'\[([^\]]+)\]',line):
            if model: yield model,fields
            model=m[1]
            fields={}
        elif model and '=' in line and not line.startswith(('#',';')):
            k,v=line.split('=',1); fields[k.strip()]=v.strip()
    if model: yield model,fields

def extract(text,major,only=None):
    rows=set()
    for section,fields in sections(text):
        model=re.sub(r'_(?:BETA|PREVIEW|PRE)$','',section)
        if only and model!=only: continue
        ver=fields.get('system_ver','')
        if not re.fullmatch(major+r'\.\d+\.\d+',ver): continue
        for k in ('firmware','firmware_x64'):
            name=fields.get(k,'')
            if ('_'+ver+'_') in name and name.lower().endswith('.bin') and official_valid(name,model):
                rows.add((name,model))
                if model=='X86':
                    rows.add((name[:-4]+'.iso',model))
    return rows

def official4(model,gw,fetcher=fetch):
    if not re.fullmatch(r'[!-~]{10,128}',gw):
        raise ValueError('invalid or missing gateway')
    n=''.join(str(b%10) for b in secrets.token_bytes(10))
    h={'X-Device-Platform':model,'X-Nonce':n,'X-Gw-Id':gw}
    msg='&'.join(f'{k}={h[k]}' for k in sorted(h))
    h.update({'X-Sign':hmac.new(gw[-10:].encode('ascii'),msg.encode('ascii'),hashlib.sha256).hexdigest(),
              'X-Version':'3.7.26','X-Version-Num':'300070026'})
    result=json.loads(fetcher(API,h))
    if not isinstance(result,dict) or result.get('code')!=0 or not isinstance(result.get('data'),dict):
        raise ValueError('official query returned no manifest')
    meta=result['data']
    link=urllib.parse.urlsplit(meta.get('fileUrl',''))
    if link.scheme!='https' or link.netloc.lower() not in (OSS,OSS+':443') or link.fragment:
        raise ValueError('unexpected manifest host')
    data=fetcher(meta['fileUrl'])
    if hashlib.md5(data).hexdigest()!=str(meta.get('md5','')).lower():
        raise ValueError('manifest digest mismatch')
    return extract(data.decode('utf-8-sig'),'4',model)

def collect(gw):
    done=set(); failed=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs={'3.x':pool.submit(lambda:extract(fetch(LEGACY).decode('utf-8-sig'),'3'))}
        for model in ('X86','X86ENT',*ALLOWED_4_MODELS):
            jobs[model]=pool.submit(official4,model,gw)
        for key,job in jobs.items():
            try:
                rows=job.result()
                if not rows: raise ValueError('no supported entries')
                done.update(rows)
                print(key, 'official files:',len(rows))
            except Exception as exc:
                failed.append(key)
                print(f'::warning::Official manifest {key}: {type(exc).__name__}; history was preserved.')
    return done,failed
