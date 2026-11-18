"""Stream a standard ZIP/DEFLATE archive; authoring only, never a player."""
from __future__ import annotations
import argparse
import binascii
import hashlib
import json
import struct
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import numpy as np
from build_demo import FFMPEG, empty_dynamic_group, stored, render

def header(crc, packed, plain, filename):
    return struct.pack('<I5H3I2H', 0x04034B50,20,0,8,0,33,
                       crc,packed,plain,len(filename),0) + filename

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--width',type=int,default=192)
    parser.add_argument('--height',type=int,default=144)
    parser.add_argument('--fps',type=int,default=30)
    parser.add_argument('--seconds',type=float,default=60)
    parser.add_argument('--start',type=float,default=0)
    parser.add_argument('--burn',type=int,default=7200)
    parser.add_argument('--pad',type=int,default=65536)
    parser.add_argument('--keep-ansi',action='store_true',help='also save the uncompressed ANSI reference (large)')
    args = parser.parse_args()
    if args.width<8 or args.height<2 or args.width%8 or args.height%2:
        parser.error('positive width divisible by 8 and positive even height are required')
    if args.fps<1 or args.seconds<=0 or args.start<0 or args.burn<0 or args.pad<0:
        parser.error('fps/duration must be positive; start/burn/pad must be nonnegative')
    if Path(args.name).name!=args.name or args.name in ('.','..'):
        parser.error('name must be a plain file stem')
    path = ROOT / 'samples' / args.name
    path.parent.mkdir(exist_ok=True)
    filename = b'badapple.ansi'
    burn = empty_dynamic_group() * args.burn
    rows = []
    checksum = 0
    output_hash = hashlib.sha256()
    plain_size = 0
    source_command = [str(FFMPEG),'-v','error','-ss',str(args.start),
        '-i',str(ROOT/'assets'/'BadApple.source.mp4'),'-t',str(args.seconds),
        '-vf',f'fps={args.fps},scale={args.width}:{args.height}:flags=area,format=gray',
        '-f','rawvideo','pipe:1']
    process = subprocess.Popen(source_command,stdout=subprocess.PIPE)
    frame_size = args.width*args.height
    expected_frames = round(args.seconds*args.fps)
    with path.with_suffix('.zip').open('w+b') as archive, \
         (path.with_suffix('.ansi').open('wb') if args.keep_ansi else nullcontext(None)) as reference, \
         path.with_suffix('.mono').open('wb') as mono:
        archive.write(header(0,0,0,filename))
        start = archive.tell()
        def output(data, final=False):
            nonlocal checksum, plain_size
            if reference is not None:reference.write(data)
            checksum = binascii.crc32(data, checksum) & 0xffffffff
            output_hash.update(data)
            plain_size += len(data)
            for offset in range(0,len(data),65535):
                archive.write(stored(data[offset:offset+65535], final=final and offset+65535>=len(data)))
        output(b'\x1b[2J\x1b[H\x1b[?25l')
        for number in range(1,expected_frames+1):
            gray = process.stdout.read(frame_size)
            if len(gray) != frame_size:
                raise RuntimeError(f'source ended early at frame {number}')
            bits = np.packbits(np.frombuffer(gray,dtype=np.uint8)>127).tobytes()
            mono.write(bits)
            packet = render(gray,number,expected_frames,args.width,args.height,args.pad)
            frame_start, plain_start = archive.tell(), plain_size
            output(packet)
            wait_start = archive.tell()
            archive.write(burn)
            rows.append({'number':number,'source_time':round(args.start+(number-1)/args.fps,6),
                'output_offset':plain_start,'output_bytes':len(packet),
                'zip_frame_start':frame_start,'zip_wait_start':wait_start,'zip_wait_end':archive.tell()})
        if process.stdout.read(1):
            raise RuntimeError('source produced more frames than expected')
        if process.wait():
            raise RuntimeError('FFmpeg failed')
        output(b'\x1b[0m\x1b[?25h\r\n',final=True)
        packed_size = archive.tell()-start
        if max(packed_size,plain_size)>=2**32:
            raise RuntimeError('ZIP64 would be required')
        central_offset = archive.tell()
        central = struct.pack('<I6H3I5H2I',0x02014B50,20,20,0,8,0,33,
            checksum,packed_size,plain_size,len(filename),0,0,0,0,0,0)+filename
        archive.write(central)
        archive.write(struct.pack('<I4H2IH',0x06054B50,0,0,1,1,len(central),central_offset,0))
        archive.seek(0)
        archive.write(header(checksum,packed_size,plain_size,filename))
    metadata = {'width':args.width,'height':args.height,'target_fps':args.fps,
        'target_seconds':args.seconds,'source_start_seconds':args.start,
        'source_url':'https://github.com/rkk-2s/bad-apple/blob/master/BadApple.mp4',
        'frame_count':expected_frames,'burn_groups_per_frame':args.burn,
        'empty_dynamic_blocks_per_frame':args.burn*4,'frame_padding_bytes':args.pad,
        'compressed_deflate_bytes':packed_size,'uncompressed_bytes':plain_size,
        'zip_bytes':path.with_suffix('.zip').stat().st_size,
        'stdout_sha256':output_hash.hexdigest(),'crc32':f'{checksum:08x}',
        'reference_monochrome':path.with_suffix('.mono').name,
        'mono_format':'row-major, white=1, most significant bit first, no per-frame padding',
        'source_command':source_command,'frames':rows}
    path.with_suffix('.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in metadata.items() if k not in ('frames','source_command')}),flush=True)

if __name__=='__main__':
    main()
