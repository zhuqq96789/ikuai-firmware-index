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

def extract_manifest(text,major,only=None,*,include_device_sections=False):
    rows=set()
    notes={}
    for section,fields in sections(text):
        section_model=re.sub(r'_(BETA|PREVIEW|PRE)$','',section,flags=re.I)
        channel=section[len(section_model)+1:].upper()
        ver=fields.get('system_ver','')
        if not re.fullmatch(major+r'\.\d+\.\d+',ver): continue
        body=re.sub(r'\\+r\\+n|\\+n|\\+r','\n',fields.get('update_content','')).strip()
        for k in ('firmware','firmware_x64'):
            name=fields.get(k,'')
            device=device_model(name)
            model=device or section_model
            if device and fields.get('firmwarename',name.split('_sysupgrade_')[0])!=name.split('_sysupgrade_')[0]:
                continue
            if only and model!=only and not (include_device_sections and device): continue
            if ('_'+ver+'_') in name and name.lower().endswith('.bin') and official_valid(name,model):
                rows.add((name,model))
                if model=='X86':
                    rows.add((name[:-4]+'.iso',model))
                build=re.search(r'_Buil(?:d)?(\d{12})\.bin$',name,re.I)
                if build and body and body not in ('无','暂无','—','-'):
                    notes[model,ver,build[1],channel]=body
    return rows,notes

def extract(text,major,only=None):
    return extract_manifest(text,major,only)[0]

def official4_text(model,gw,fetcher=fetch):
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
    return data.decode('utf-8-sig')

def official4(model,gw,fetcher=fetch,*,include_device_sections=False):
    return extract_manifest(official4_text(model,gw,fetcher),'4',model,
                            include_device_sections=include_device_sections)

def collect(gw,known3=(),known4=()):
    done=set(); notes={}; failed=[]
    def get(jobs,*,allow_empty=False):
        rows=set()
        for key,job in jobs.items():
            try:
                found,logs=job.result()
                if not found:
                    if allow_empty:continue
                    raise ValueError('no supported entries')
                rows.update(found)
                notes.update(logs)
                print(key, 'official files:',len(found),'release notes:',len(logs))
            except Exception as exc:
                failed.append(key)
                print(f'::warning::Official manifest {key}: {type(exc).__name__}; history was preserved.')
        return rows
    with ThreadPoolExecutor(max_workers=8) as pool:
        early3=pool.submit(lambda:extract_manifest(fetch(LEGACY).decode('utf-8-sig'),'3'))
        early4={p:pool.submit(official4,p,gw,include_device_sections=True) for p in ('X86','X86ENT')}
        rows3=get({'3.x':early3})
        rows4=get(early4)
        done.update(rows3|rows4)
        advertised={model for name,model in rows4 if device_model(name)}
        devices3={model for name,model in rows3 if device_model(name)}
        # An existing 3.x device may later publish its first 4.x build only
        # through the dedicated model manifest, without appearing in x86 feeds.
        models=sorted(set(ALLOWED_4_MODELS)|set(known3)|set(known4)|advertised|devices3)
        done.update(get({p:pool.submit(official4,p,gw) for p in models},allow_empty=True))
    return done,notes,failed
