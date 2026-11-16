import argparse
import datetime as dt
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from index_format import decode, encode, normalize, PROJECTS
from source_collect import online, combine

ROOT=Path(__file__).resolve().parents[1]

def update(path, fetch=online):
    previous=path.read_bytes() if path.exists() else b''
    saved_date, known=decode(previous) if previous else ('',[])
    previous_by_source={p:[] for p in PROJECTS}
    for e in known:
        for r in e['refs']:
            previous_by_source[r['project']].append(dict(r,filename=e['filename']))
    rows, failures = [], []
    with ThreadPoolExecutor(max_workers=3) as ex:
        tasks={p:ex.submit(fetch,p,builtin=previous_by_source[p]) for p in PROJECTS}
        for p in PROJECTS:
            old=previous_by_source[p]
            try:
                new=tasks[p].result()
                before=len({r['filename'].casefold() for r in old})
                after=len({r['filename'].casefold() for r in new})
                if after==0 or (before and after<before*.7):
                    raise ValueError('Unexpected source inventory size')
                rows.extend(new)
                print(f'{p}: {after} firmware files')
            except Exception as exc:
                failures.append(p)
                rows.extend(old)
                print(f'::warning::{p} retained previous entries ({type(exc).__name__}).')
    if len(failures)==len(PROJECTS):
        raise RuntimeError('All sources failed; previous history.txt is unchanged.')
    combined=normalize(combine(rows))
    if combined==known:
        print(f'No changes. {len(combined)} unique firmware entries.')
        return failures
    day=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    data=encode(combined,day).encode('utf-8')
    assert decode(data)==(day,combined)
    tmp=path.with_suffix('.tmp')
    tmp.write_bytes(data)
    tmp.replace(path)
    print(f'Updated history.txt: {len(combined)} unique firmware entries.')
    return failures

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--path',type=Path,default=ROOT/'history.txt')
    p.add_argument('--check',action='store_true')
    args=p.parse_args()
    if args.check:
        day,rows=decode(args.path.read_bytes())
        print(f'{day}: {len(rows)} unique firmware entries')
    else:
        update(args.path)

if __name__=='__main__':
    main()
