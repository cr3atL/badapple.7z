"""Passively verify stock 7-Zip output without saving it or pacing its frames."""
import argparse
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import zipfile

MARKER=re.compile(rb'\x1b\]0;Bad Apple \| frame (\d+)/(\d+)\x07')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive',type=Path);p.add_argument('--tool',default=os.environ.get('SEVENZIP_BINARY'))
    p.add_argument('--report',type=Path)
    a=p.parse_args();path=a.archive.resolve()
    tool=a.tool or shutil.which('7z') or shutil.which('7zz')
    if not tool and os.name=='nt':tool=str(Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'7-Zip'/'7z.exe')
    if not tool:p.error('Install stock 7-Zip, or pass --tool /path/to/7z')
    with zipfile.ZipFile(path) as archive:
        entries=archive.infolist();assert len(entries)==1 and entries[0].compress_type==8
        info=entries[0]
    metadata=json.loads(path.with_suffix('.json').read_text(encoding='utf-8')) if path.with_suffix('.json').is_file() else {}
    expected_frames=metadata.get('frame_count') or len(metadata.get('frames',[]))
    command=[tool,'x','-so','-bd','-bsp0',str(path)]
    start=time.perf_counter();digest=hashlib.sha256();crc=0;count=0;tail=b'';events=[]
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
    while chunk:=os.read(process.stdout.fileno(),65536):
        now=time.perf_counter()-start;digest.update(chunk);crc=binascii.crc32(chunk,crc);count+=len(chunk)
        for m in MARKER.finditer(tail+chunk):
            number=int(m[1]);total=int(m[2])
            if not events or events[-1]['number']!=number:events.append({'number':number,'seconds':round(now,7)})
            if not expected_frames:expected_frames=total
            assert total==expected_frames
        tail=(tail+chunk)[-80:]
    code=process.wait();stderr=process.stderr.read().decode(errors='replace')
    elapsed=time.perf_counter()-start;actual=digest.hexdigest()
    assert code==0,stderr
    assert count==info.file_size and (crc&0xffffffff)==info.CRC
    assert expected_frames and [e['number'] for e in events]==list(range(1,expected_frames+1))
    if metadata.get('stdout_sha256'):assert actual==metadata['stdout_sha256']
    report={'archive':path.name,'stock_tool':Path(tool).name,'exit_code':code,'frame_count':len(events),
        'elapsed_seconds':elapsed,'observed_marker_fps':(len(events)-1)/(events[-1]['seconds']-events[0]['seconds']) if len(events)>1 and events[-1]['seconds']>events[0]['seconds'] else None,
        'stdout_bytes':count,'stdout_sha256':actual,'crc32':f'{crc&0xffffffff:08x}',
        'crc_and_size_match_zip':True,'complete_frame_sequence':True,
        'observer':'Passive blocking reads and hashes. No sleeps, frame scheduling, rendering or playback acknowledgements.',
        'timing_basis':'stdout marker arrival in this observer, not terminal paint timestamps.','frames':events}
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='frames'}))

if __name__=='__main__':main()
