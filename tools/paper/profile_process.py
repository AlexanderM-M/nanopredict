"""Sample Linux /proc process-tree resources; retain raw samples, do not infer live latency."""
import argparse
import csv
import os
import time
from pathlib import Path


def processes():
    result={}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit(): continue
        try:
            raw=(path/'stat').read_text(); fields=raw[raw.rindex(')')+2:].split()
            result[int(path.name)]={'ppid':int(fields[1]),'ticks':int(fields[11])+int(fields[12]),
                                    'start_ticks':int(fields[19]),'rss_bytes':int(fields[21])*os.sysconf('SC_PAGE_SIZE')}
        except (OSError,ValueError,IndexError): continue
    return result


def tree(table,pid):
    selected={pid}; previous=set()
    while previous!=selected:
        previous=set(selected); selected.update(p for p,r in table.items() if r['ppid'] in selected)
    return [r for p,r in table.items() if p in selected]


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--pid',type=int,required=True)
    p.add_argument('--seconds',type=float,required=True); p.add_argument('--interval',type=float,default=1.)
    p.add_argument('--output',type=Path,required=True); a=p.parse_args()
    if not Path('/proc/self/stat').exists(): p.error('Linux /proc is required')
    if not 0<a.interval<=a.seconds or a.pid<=0: p.error('Require positive PID and 0 < interval <= duration')
    initial=processes()
    if a.pid not in initial: p.error('Process does not exist or cannot be read')
    start_ticks=initial[a.pid]['start_ticks']; start=time.monotonic()
    with a.output.open('x',newline='') as handle:
        w=csv.DictWriter(handle,fieldnames=['elapsed_seconds','processes','sum_rss_bytes','sum_lifetime_cpu_seconds','root_alive']); w.writeheader()
        while True:
            table=processes(); root=table.get(a.pid); alive=root is not None and root['start_ticks']==start_ticks
            rows=tree(table,a.pid) if alive else []; elapsed=time.monotonic()-start
            w.writerow({'elapsed_seconds':elapsed,'processes':len(rows),'sum_rss_bytes':sum(r['rss_bytes'] for r in rows),
                        'sum_lifetime_cpu_seconds':sum(r['ticks'] for r in rows)/os.sysconf('SC_CLK_TCK'),'root_alive':alive}); handle.flush()
            if not alive or elapsed>=a.seconds: break
            time.sleep(min(a.interval,a.seconds-elapsed))


if __name__=='__main__': main()
