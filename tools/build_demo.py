"""Build a native-DEFLATE playback experiment. This is an offline authoring tool."""

from __future__ import annotations

import argparse
import binascii
import json
import struct
import subprocess
import time
from pathlib import Path
from tool_paths import find_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = find_ffmpeg()


def empty_dynamic_group() -> bytes:
    """Four valid empty dynamic-Huffman blocks, together byte aligned (45 B)."""
    bits: list[int] = []

    def put(value: int, size: int) -> None:
        bits.extend((value >> i) & 1 for i in range(size))

    order = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1]
    for _ in range(4):
        put(4, 3)  # non-final dynamic block
        put(0, 5)  # 257 literal/length codes
        put(0, 5)  # one distance code
        put(14, 4)  # 18 code-length alphabet entries
        for symbol in order:
            put(int(symbol in (1, 18)), 3)
        put(1, 1)  # code 18: 138 zero lengths
        put(127, 7)
        put(1, 1)  # code 18: another 118 zero lengths
        put(107, 7)
        put(0, 1)  # literal code 256 has length one
        put(0, 1)  # distance code zero has length one
        put(0, 1)  # end of block, no output
    assert len(bits) == 360
    return bytes(sum(bits[j + i] << i for i in range(8)) for j in range(0, len(bits), 8))


def stored(data: bytes, final: bool = False) -> bytes:
    if len(data) > 65535:
        raise ValueError("Stored block exceeds 65535 bytes")
    return bytes([int(final)]) + struct.pack("<HH", len(data), len(data) ^ 0xFFFF) + data


def write_containers(name: str, raw: bytes, plain: bytes, metadata: dict) -> None:
    path = ROOT / "samples" / name
    crc = binascii.crc32(plain) & 0xFFFFFFFF
    filename = b"badapple.ansi"
    # Fixed DOS timestamp: 1980-01-01 00:00:00. No executable or extraction hooks.
    local = struct.pack("<I5H3I2H", 0x04034B50, 20, 0, 8, 0, 33,
                        crc, len(raw), len(plain), len(filename), 0) + filename
    central = struct.pack("<I6H3I5H2I", 0x02014B50, 20, 20, 0, 8, 0, 33,
                          crc, len(raw), len(plain), len(filename), 0, 0, 0, 0, 0, 0) + filename
    end = struct.pack("<I4H2IH", 0x06054B50, 0, 0, 1, 1, len(central), len(local) + len(raw), 0)
    path.with_suffix(".zip").write_bytes(local + raw + central + end)
    gzip_header = bytes.fromhex("1f8b0800000000000003")
    path.with_suffix(".gz").write_bytes(gzip_header + raw + struct.pack("<II", crc, len(plain) & 0xFFFFFFFF))
    path.with_suffix(".json").write_text(json.dumps(metadata | {
        "compressed_deflate_bytes": len(raw), "uncompressed_bytes": len(plain),
        "crc32": f"{crc:08x}", "generated_unix_time": time.time(),
    }, indent=2), encoding="utf-8")
    path.with_suffix(".ansi").write_bytes(plain)
    print(json.dumps({"zip": str(path.with_suffix('.zip')), "compressed_bytes": len(raw),
                      "output_bytes": len(plain), "frames": len(metadata.get('frames', []))}))


def get_frames(start: float, duration: float, fps: int, width: int, height: int) -> list[bytes]:
    cmd = [str(FFMPEG), "-v", "error", "-ss", str(start), "-i", str(ROOT / "assets/BadApple.source.mp4"),
           "-t", str(duration), "-vf", f"fps={fps},scale={width}:{height}:flags=area,format=gray",
           "-f", "rawvideo", "pipe:1"]
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE)
    size = width * height
    return [result.stdout[i:i + size] for i in range(0, len(result.stdout) - size + 1, size)]


def render(frame: bytes, number: int, total: int, width: int, height: int, pad: int) -> bytes:
    # OSC title provides observable frame markers and changes the native terminal title.
    title = f"\x1b]0;Bad Apple | frame {number:03d}/{total:03d}\x07"
    lines = []
    glyphs = [" ", "▀", "▄", "█"]
    for y in range(0, height, 2):
        lines.append("".join(glyphs[int(frame[y * width + x] > 127) |
                                    (int(frame[(y + 1) * width + x] > 127) << 1)]
                             for x in range(width)))
    body = (title + "\x1b[H\x1b[97;40m" + "\r\n".join(lines)).encode("utf-8")
    # NUL is ignored by VT terminals. It forces native output buffers to fill; no waiting.
    if pad:
        body += b"\0" * max(0, pad - len(body))
    return body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="badapple-3s")
    parser.add_argument("--burn", type=int, default=30000, help="45-byte empty-block groups per frame")
    parser.add_argument("--pad", type=int, default=65536, help="minimum output bytes per frame")
    parser.add_argument("--fps", type=int, default=6)
    parser.add_argument("--seconds", type=float, default=3)
    parser.add_argument("--start", type=float, default=30)
    parser.add_argument("--width", type=int, default=64)
    parser.add_argument("--height", type=int, default=48)
    parser.add_argument("--probe", action="store_true", help="emit frame labels without video extraction")
    args = parser.parse_args()
    if args.width<1 or args.height<2 or args.height%2 or args.fps<1 or args.seconds<=0 or args.burn<0 or args.pad<0:
        parser.error('positive dimensions/fps/duration, even height and nonnegative burn/pad are required')
    if Path(args.name).name != args.name or args.name in ('.','..'):
        parser.error('name must be a plain file stem')
    (ROOT / "samples").mkdir(exist_ok=True)
    if args.probe:
        frames = [bytes([255 if i % 2 else 0]) * args.width * args.height for i in range(6)]
    else:
        frames = get_frames(args.start, args.seconds, args.fps, args.width, args.height)
    raw_parts = []
    output_parts = []
    initial = b"\x1b[2J\x1b[H\x1b[?25l"
    raw_parts.append(stored(initial))
    output_parts.append(initial)
    burn = empty_dynamic_group() * args.burn
    rows = []
    for i, frame in enumerate(frames, 1):
        output = render(frame, i, len(frames), args.width, args.height, args.pad)
        for offset in range(0, len(output), 65535):
            raw_parts.append(stored(output[offset:offset + 65535]))
        output_parts.append(output)
        raw_parts.append(burn)
        rows.append({"number": i, "source_time": args.start + (i - 1) / args.fps,
                     "output_bytes": len(output), "gray": frame.hex()})
    final = b"\x1b[0m\x1b[?25h\r\n"
    raw_parts.append(stored(final, final=True))
    output_parts.append(final)
    write_containers(args.name, b"".join(raw_parts), b"".join(output_parts), {
        "source_url": "https://github.com/rkk-2s/bad-apple/blob/master/BadApple.mp4",
        "width": args.width, "height": args.height, "target_fps": args.fps,
        "target_seconds": args.seconds, "burn_groups_per_frame": args.burn,
        "frame_padding_bytes": args.pad, "frames": rows,
    })


if __name__ == "__main__":
    main()
