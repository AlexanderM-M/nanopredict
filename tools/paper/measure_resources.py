"""Measure one finite POSIX command; does not infer live latency from process runtime."""
import argparse
import json
import platform
import resource
import subprocess
import time
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('command',nargs=argparse.REMAINDER)
    a=p.parse_args(); command=a.command
    if command and command[0]=='--': command=command[1:]
    if not command: p.error('Provide a finite command after --')
    before=resource.getrusage(resource.RUSAGE_CHILDREN); start=time.perf_counter()
    result=subprocess.run(command,check=False)
    elapsed=time.perf_counter()-start; after=resource.getrusage(resource.RUSAGE_CHILDREN)
    data={'command':command,'exit_code':result.returncode,'wall_seconds':elapsed,'child_user_seconds':after.ru_utime-before.ru_utime,'child_system_seconds':after.ru_stime-before.ru_stime,'max_rss_native':after.ru_maxrss,'max_rss_unit':'bytes' if platform.system()=='Darwin' else 'KiB','platform':platform.platform(),'limitation':'RUSAGE_CHILDREN process-tree accounting; peak RSS is not simultaneous aggregate memory across workers. This finite command is not live-run latency or sequencer overhead.'}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(data,indent=2)+'\n')
    raise SystemExit(result.returncode)


if __name__=='__main__': main()
