"""Locate and validate original firmware for the repository's release archive."""
import gzip
import hashlib
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from catalog_format import catalog_decode, device_model
from index_format import PC

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 512 * 1024**2
HEADER = bytes.fromhex('1f8b08006f9b4b590203')
STATE = Path('data/release-archive.json')
OFFICIAL = 'https://patch.ikuai8.com/'
PUBLIC_HOSTS = {'patch.ikuai8.com','github.com','raw.githubusercontent.com',
                'media.githubusercontent.com','objects.githubusercontent.com',
                'release-assets.githubusercontent.com','github-releases.githubusercontent.com',
                'github-cloud.s3.amazonaws.com'}


def catalog(root=ROOT):
    _, archive, official = catalog_decode((root/'data/catalog.json').read_bytes())
    entries = {e['filename']:e['refs'] for e in archive}
    for n, _ in official:
        entries.setdefault(n,[])
    return entries


def public_url(name):
    model = device_model(name)
    if model:
        return OFFICIAL+'firmware/'+name.split('_')[0]+'/'+name if '_3.' in name else ''
    if '_enterprise_' in name.lower():
        return OFFICIAL+'ent/'+name if '_3.' in name and name.lower().endswith('.bin') else ''
    return OFFICIAL+'3.x/'+('iso/' if name.lower().endswith('.iso') else 'patch/')+name


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        u = urllib.parse.urlsplit(newurl)
        if u.scheme != 'https' or u.netloc not in PUBLIC_HOSTS:
            raise ValueError('unexpected firmware redirect')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def open_public(url,headers=None,timeout=20):
    u = urllib.parse.urlsplit(url)
    if u.scheme != 'https' or u.netloc not in PUBLIC_HOSTS:
        raise ValueError('unexpected firmware host')
    req = urllib.request.Request(url,headers={'User-Agent':'iKuai-archive','Accept-Encoding':'identity',**(headers or {})})
    return urllib.request.build_opener(Redirect()).open(req,timeout=timeout)


def read_header(stream):
    offset = int.from_bytes(stream.read(4),'big')
    if not 10 <= offset <= 1024**2:raise ValueError('invalid BIN header')
    data = stream.read(offset)
    if len(data) != offset:raise ValueError('short BIN header')
    with gzip.GzipFile(fileobj=io.BytesIO(HEADER+data)) as z:
        decoded = z.read(1024**2+1)
    if len(decoded)>1024**2:raise ValueError('BIN metadata too large')
    return json.loads(decoded)


def iso_descriptor(blob):
    return any(blob[k:k+7] == b'\x01CD001\x01' for k in range(0,len(blob)-6,2048))


def inspect_direct(name):
    url = public_url(name)
    if not url:return 'missing'
    iso = name.lower().endswith('.iso')
    start, end = (32768,65535) if iso else (0,4095)
    try:
        with open_public(url,{'Range':f'bytes={start}-{end}'},timeout=8) as r:
            if r.status == 206:
                q = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',r.headers.get('Content-Range',''))
                if not q or int(q[3])<1024**2 or (int(q[1]),int(q[2]))!=(start,end):return 'missing'
            elif r.status == 200:
                if 'text/html' in r.headers.get('Content-Type','') or int(r.headers.get('Content-Length') or 0)<1024**2:return 'missing'
                if start and len(r.read(start))!=start:return 'missing'
            else:return 'retry'
            raw=r.read(end-start+1)
        if iso:return 'public' if iso_descriptor(raw) else 'missing'
        meta=read_header(io.BytesIO(raw))
        return 'public' if meta.get('filename')==name and int(meta.get('length',0))>=1024**2 else 'missing'
    except urllib.error.HTTPError as exc:
        return 'missing' if exc.code in (403,404,410,416) else 'retry'
    except (OSError,EOFError,TypeError,ValueError):
        return 'retry'


def verify_file(file,name,expected=''):
    size=file.stat().st_size
    if not 1024**2<size<=LIMIT:raise ValueError('firmware size invalid')
    whole=hashlib.sha256()
    with file.open('rb') as f:
        for block in iter(lambda:f.read(1024**2),b''):whole.update(block)
        sha=whole.hexdigest()
        if expected and expected!=sha:raise ValueError('mirror SHA-256 mismatch')
        if name.lower().endswith('.iso'):
            f.seek(32768)
            if not iso_descriptor(f.read(32768)):raise ValueError('invalid ISO9660')
        else:
            f.seek(0)
            meta=read_header(f)
            if meta.get('filename')!=name or int(meta.get('length',0))!=size-f.tell():
                raise ValueError('BIN name or payload length mismatch')
            if str(meta.get('ext','0'))!='0':raise ValueError('unsupported BIN wrapper')
            digest, strong=hashlib.md5(),hashlib.sha256()
            for block in iter(lambda:f.read(1024**2),b''):
                digest.update(block)
                strong.update(block)
            if meta.get('md5','').lower()!=digest.hexdigest():raise ValueError('BIN payload MD5 mismatch')
            inner=meta.get('sha256','').lower()
            if inner and (len(inner) not in (32,64) or not strong.hexdigest().startswith(inner)):
                raise ValueError('BIN payload SHA-256 mismatch')
    return sha,size

def tag_for(name):
    suffix = 'devices' if device_model(name) else 'x86'
    return 'firmware-v'+name.split('_')[2][0]+'-'+suffix


def transfer(response,destination):
    total=0
    with response as src,destination.open('wb') as out:
        size = src.headers.get('Content-Length')
        if size and not 1024**2<int(size)<=LIMIT:raise ValueError('unexpected firmware transfer length')
        for chunk in iter(lambda:src.read(1024**2),b''):
            total+=len(chunk)
            if total>LIMIT:raise ValueError('download too large')
            out.write(chunk)
        if size and total!=int(size):raise ValueError('short firmware transfer')


def state_read(root):
    path=root/STATE
    if not path.exists():return {'schema':1,'archived':{},'public':[],'pending':[]}
    obj=json.loads(path.read_bytes())
    if obj.get('schema')!=1:raise ValueError('invalid archive state')
    return obj


def state_write(root,state):
    path=root/STATE
    data=(json.dumps(state,ensure_ascii=True,sort_keys=True,separators=(',',':'))+'\n').encode()
    if path.is_file() and path.read_bytes()==data:return
    temp=path.with_suffix('.tmp')
    temp.write_bytes(data)
    temp.replace(path)


class Github:
    def __init__(self,repo,token):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo) or not token:
            raise ValueError('GitHub repository and token required')
        self.repo = repo
        self.base = 'https://api.github.com/repos/'+repo
        self.headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'iKuai-archive',
                      'X-GitHub-Api-Version':'2022-11-28'}

    def api(self,path,method='GET',data=None):
        req=urllib.request.Request(self.base+path,data=None if data is None else json.dumps(data).encode(),
            method=method,headers={**self.headers,'Content-Type':'application/json'})
        # No source host can redirect a request carrying this token.
        from official import NoRedirect
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=18) as res:
            return json.load(res) if res.status!=204 else None

    def releases(self):
        states={}
        for suffix in ('v3-x86','v4-x86','v3-devices','v4-devices'):
            tag='firmware-'+suffix
            try:release=self.api('/releases/tags/'+tag)
            except urllib.error.HTTPError as e:
                if e.code==404:continue
                raise
            assets={}
            for page in range(1,12):
                rows=self.api(f'/releases/{release["id"]}/assets?per_page=100&page={page}')
                assets.update({r['name']:r for r in rows if r['state']=='uploaded'})
                if len(rows)<100:break
            states[tag]=(release,assets)
        return states

    def release(self,tag):
        labels={'v3-x86':'3.x x86','v4-x86':'4.x x86','v3-devices':'3.x 官方设备','v4-devices':'4.x 官方设备'}
        try:
            return self.api('/releases','POST',{
                'tag_name':tag,'name':labels[tag.removeprefix('firmware-')]+' 固件归档',
                'body':'收录当前没有可用公开官方直链、且通过完整性校验的原始固件。文件名保留原样。',
                'make_latest':'false',
            })
        except urllib.error.HTTPError as exc:
            if exc.code!=422:raise
            return self.api('/releases/tags/'+tag)

    def upload(self,release,file,sha,size,name):
        import http.client
        u=urllib.parse.urlsplit(release['upload_url'].split('{',1)[0])
        if (u.scheme,u.netloc,u.path)!=('https','uploads.github.com',f'/repos/{self.repo}/releases/{release["id"]}/assets'):
            raise ValueError('invalid release upload endpoint')
        conn=http.client.HTTPSConnection(u.netloc,timeout=160,blocksize=1024**2)
        try:
            with file.open('rb') as stream:
                conn.request('POST',u.path+'?'+urllib.parse.urlencode({'name':name}),stream,
                             {**self.headers,'Content-Type':'application/octet-stream','Content-Length':str(size)})
                res=conn.getresponse()
                if res.status!=201:raise RuntimeError(f'GitHub upload HTTP {res.status}')
                out=json.load(res)
        finally:conn.close()
        if out.get('name')!=name or out.get('size')!=size or out.get('state')!='uploaded':
            raise ValueError('GitHub did not confirm the expected release asset')
        if out.get('digest') and out['digest']!='sha256:'+sha:raise ValueError('GitHub release digest differs')
        return out


def obtain(name,refs,destination,local_dirs=(),authorized=None):
    for location in local_dirs:
        p=location/name
        if p.is_file():
            try:return p,*verify_file(p,name)
            except (OSError,EOFError,TypeError,ValueError):pass
    for ref in sorted((x for x in refs if x['url']),key=lambda r:not bool(r['sha256'])):
        try:
            transfer(open_public(ref['url'],timeout=25),destination)
            return destination,*verify_file(destination,name,ref['sha256'])
        except (OSError,EOFError,TypeError,ValueError):pass
    if authorized and '_4.' in name:
        try:
            transfer(authorized(name),destination)
            return destination,*verify_file(destination,name)
        except (OSError,EOFError,TypeError,ValueError):pass
    return None


class AuthorizedSource:
    def __init__(self,gateway,certificate,key,ca=None):
        import ssl
        from threading import Lock
        if not re.fullmatch(r'[!-~]{10,128}',gateway):raise ValueError('invalid gateway ID')
        self.gateway=gateway
        self.context=ssl.create_default_context(cafile=str(ca) if ca else None)
        if ca:self.context.verify_flags&=~ssl.VERIFY_X509_STRICT
        self.context.load_cert_chain(str(certificate),str(key),password='')
        self.lock=Lock()

    def __call__(self,name):
        import hmac,secrets
        from official import NoRedirect
        if '_4.' not in name or not name.lower().endswith('.bin'):raise ValueError('unsupported authorized package')
        model=device_model(name)
        work='enterprise' if model or '_enterprise_' in name.lower() else 'community'
        if model:
            platform='arm'
            path=f'/firmware/{work}/arm/{model.lower()}/{name}'
        else:
            match=PC.fullmatch(name)
            if not match:raise ValueError('invalid x86 filename')
            platform='x86-64' if '_x64_' in name.lower() else 'x86-32'
            path=None
            model='X86ENT' if work=='enterprise' else 'X86'
        for attempt in range(2):
            with self.lock:
                fields={'X-Device-Platform':platform,'X-System-Version':work,'X-Model-Type':model,
                        'X-Firmware-Name':name,'X-Gw-Id':self.gateway,'X-Nonce':secrets.token_hex(5)}
                fields['X-Nonce']=''.join(str(int(c,16)%10) for c in fields['X-Nonce'])
                canonical='&'.join(f'{k}={fields[k]}' for k in sorted(fields)).encode('ascii')
                fields['X-Sign']=hmac.new(self.gateway[-10:].encode('ascii'),canonical,hashlib.sha256).hexdigest()
                opener=urllib.request.build_opener(NoRedirect())
                req=urllib.request.Request('https://devapi.ikuai8.com/firmware/sign-url',headers=fields,data=b'')
                with opener.open(req,timeout=13) as f:
                    result=json.loads(f.read(65536))
                if result.get('code')!=0 or not isinstance(result.get('data'),dict):
                    raise ValueError('authorization did not return a download')
                url=result['data'].get('signUrl','')
                token=result['data'].get('token','')
                u=urllib.parse.urlsplit(url)
                if (u.scheme!='https' or u.netloc!='fw-download.ikuai8.com' or u.fragment
                    or not u.path.startswith('/firmware/'+work+'/') or u.path.rsplit('/',1)[-1]!=name
                    or (path is not None and u.path!=path) or not isinstance(token,str)
                    or not re.fullmatch(r'[!-~]{1,8192}',token)):
                    raise ValueError('unexpected authorized source')
                req=urllib.request.Request(url,headers={'X-Gw-Id':self.gateway,'X-Auth-Token':token,
                    'Accept-Encoding':'identity'})
                try:
                    return urllib.request.build_opener(NoRedirect(),
                        urllib.request.HTTPSHandler(context=self.context)).open(req,timeout=25)
                except urllib.error.HTTPError as e:
                    if e.code!=403 or attempt:raise


def run(root,github,*,local_dirs=(),authorized=None,import_audit=None,workers=5,limit=0):
    from tempfile import TemporaryDirectory
    from threading import Lock
    old=state_read(root)
    entries=catalog(root)
    archived=dict(old['archived'])
    public=set(old['public'])
    definitely_missing=set(old.get('pending',[]))
    if import_audit:
        for name,status in import_audit.items():
            if name not in entries:continue
            if status=='public':public.add(name);definitely_missing.discard(name)
            elif status=='missing':definitely_missing.add(name);public.discard(name)
    remote=github.releases()
    for name,(tag,sha,size) in list(archived.items()):
        asset=remote.get(tag,({},{}))[1].get(name)
        if not asset or asset.get('size')!=size or asset.get('digest') not in (None,'','sha256:'+sha):
            archived.pop(name)
    checks=sorted(set(entries)-set(archived)-public-definitely_missing)
    with ThreadPoolExecutor(max_workers=10) as executor:
        for name,status in zip(checks,executor.map(inspect_direct,checks)):
            if status=='public':public.add(name)
            if status=='missing':definitely_missing.add(name)
    pending=sorted(definitely_missing-set(archived),
                   key=lambda n:(not any(r['url'] for r in entries.get(n,[])),n))
    if limit:pending=pending[:limit]
    lock=Lock()
    errors=[]
    planned = [n for n in pending if n in entries and (authorized and '_4.' in n or
                    any(r['url'] for r in entries[n]) or any((folder/n).is_file() for folder in local_dirs) or
                    n in remote.get(tag_for(n),({},{}))[1])]
    print(f'Confirmed direct {len(public)}; no public link {len(definitely_missing)}; new upload candidates with sources {len(planned)}.',flush=True)
    def save():
        state_write(root,{'schema':1,'archived':archived,'public':sorted(public),
                          'pending':sorted(definitely_missing-set(archived))})
    save()
    with TemporaryDirectory(prefix='ikuai-release-') as scratch, ThreadPoolExecutor(max_workers=workers) as pool:
        def archive_one(name):
            tag=tag_for(name)
            dest=Path(scratch)/name
            try:
                with lock:
                    asset=remote.get(tag,({},{}))[1].get(name)
                if asset:
                    recorded=asset.get('digest') or ''
                    if re.fullmatch(r'sha256:[a-f0-9]{64}',recorded):
                        sha,size=recorded[7:],asset['size']
                    else:
                        transfer(open_public(asset['browser_download_url'],timeout=45),dest)
                        sha,size=verify_file(dest,name)
                else:
                    result=obtain(name,entries[name],dest,local_dirs,authorized)
                    if not result:return
                    path,sha,size=result
                    with lock:
                        if tag not in remote:remote[tag]=(github.release(tag),{})
                        release=remote[tag][0]
                    asset=github.upload(release,path,sha,size,name)
                with lock:
                    remote[tag][1][name]=asset
                    archived[name]=[tag,sha,size]
                    save()
                    print('Archived',name,size,flush=True)
            except Exception as exc:
                with lock:
                    errors.append((name,type(exc).__name__))
                    print(f'::warning::Archive failed for {name}: {type(exc).__name__}',flush=True)
            finally:dest.unlink(missing_ok=True)
        list(pool.map(archive_one,planned))
    save()
    print(f'Release assets {len(archived)}; pending {len(definitely_missing-set(archived))}; upload errors {len(errors)}.',flush=True)


def main():
    import argparse,os
    from tempfile import TemporaryDirectory
    args=argparse.ArgumentParser()
    args.add_argument('--workers',type=int,default=4)
    args.add_argument('--audit',type=Path)
    cfg=args.parse_args()
    audit=dict(map(json.loads,cfg.audit.read_text().splitlines())) if cfg.audit else None
    github=Github(os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_TOKEN'])
    cert,key,ca=(os.environ.get('IKUAI_ARCHIVE_'+k) for k in ('CERT','KEY','CA'))
    with TemporaryDirectory(prefix='ikuai-credentials-') as t:
        authorized=None
        if cert and key:
            paths=[]
            for label,value in (('cert',cert),('key',key),('ca',ca)):
                path=Path(t)/(label+'.pem')
                if value:
                    path.write_text(value,encoding='ascii')
                    path.chmod(0o600)
                    paths.append(path)
                else:paths.append(None)
            authorized=AuthorizedSource(os.environ['IKUAI_INDEX_GATEWAY'],*paths)
        run(ROOT,github,authorized=authorized,import_audit=audit,workers=cfg.workers)


if __name__=='__main__':main()
