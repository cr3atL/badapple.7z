"""Portable authoring-tool discovery. Not imported by the native player."""
import os
from pathlib import Path
import shutil

def find_ffmpeg():
    configured=os.environ.get('FFMPEG_BINARY')
    if configured:
        resolved=shutil.which(configured) or (configured if Path(configured).is_file() else None)
        if not resolved:raise RuntimeError('FFMPEG_BINARY does not point to an executable')
        return Path(resolved)
    installed=shutil.which('ffmpeg')
    if installed:return Path(installed)
    try:
        import imageio_ffmpeg
        return Path(imageio_ffmpeg.get_ffmpeg_exe())
    except ImportError:
        raise RuntimeError('Install FFmpeg, set FFMPEG_BINARY, or pip install -r requirements-build.txt') from None
