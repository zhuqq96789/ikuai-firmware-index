import hashlib,hmac,json,re,secrets,urllib.error,urllib.parse,urllib.request
from concurrent.futures import ThreadPoolExecutor
from catalog_format import ALLOWED_4_MODELS, device_model, official_valid
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
        section_model=re.sub(r'_(?:BETA|PREVIEW|PRE)$','',section,flags=re.I)
        ver=fields.get('system_ver','')
        if not re.fullmatch(major+r'\.\d+\.\d+',ver): continue
        for k in ('firmware','firmware_x64'):
            name=fields.get(k,'')
            model=device_model(name) or section_model
            if device_model(name) and fields.get('firmwarename',name.split('_sysupgrade_')[0])!=name.split('_sysupgrade_')[0]:
                continue
            if only and model!=only: continue
            if ('_'+ver+'_') in name and name.lower().endswith('.bin') and official_valid(name,model):
                rows.add((name,model))
                if model=='X86':
                    rows.add((name[:-4]+'.iso',model))
    return rows

def official4(model,gw,fetcher=fetch,*,include_device_sections=False):
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
    entries=extract(data.decode('utf-8-sig'),'4',None if include_device_sections else model)
    if include_device_sections:
        entries={r for r in entries if r[1]==model or device_model(r[0])}
    return entries

def collect(gw,known3=(),known4=()):
    done=set(); failed=[]
    def get(jobs):
        rows=set()
        for key,job in jobs.items():
            try:
                found=job.result()
                if not found: raise ValueError('no supported entries')
                rows.update(found)
                print(key, 'official files:',len(found))
            except Exception as exc:
                failed.append(key)
                print(f'::warning::Official manifest {key}: {type(exc).__name__}; history was preserved.')
        return rows
    with ThreadPoolExecutor(max_workers=8) as pool:
        early3=pool.submit(lambda:extract(fetch(LEGACY).decode('utf-8-sig'),'3'))
        early4={p:pool.submit(official4,p,gw,include_device_sections=True) for p in ('X86','X86ENT')}
        rows3=get({'3.x':early3})
        rows4=get(early4)
        done.update(rows3|rows4)
        advertised={model for name,model in rows4 if device_model(name)}
        new3={model for name,model in rows3 if device_model(name)}-set(known3)
        models=sorted(set(ALLOWED_4_MODELS)|set(known4)|advertised|new3)
        done.update(get({p:pool.submit(official4,p,gw) for p in models}))
    return done,failed
