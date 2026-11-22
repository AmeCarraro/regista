"""Bounded local video previews. Originals are read without transcoding or rewriting them."""
from datetime import datetime
import io
import os
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw, ImageOps


def binary():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(arguments, timeout=30):
    flags = {'creationflags': 0x08000000} if os.name == 'nt' else {}
    return subprocess.run([binary(), '-hide_banner', '-nostdin', *arguments], capture_output=True, timeout=timeout, **flags)


def probe(path):
    # FFmpeg reports metadata without decoding the entire file when no output is supplied.
    result = run(['-protocol_whitelist', 'file,pipe', '-i', str(Path(path).resolve())])
    text = result.stderr.decode(errors='replace')
    stream = next((line for line in text.splitlines() if 'Video:' in line), '')
    size = re.search(r'(?<![\w:])(\d{2,6})x(\d{2,6})(?!\d)', stream)
    if not size:
        raise ValueError('Nessuna traccia video leggibile. Il file resta da catalogare.')
    duration = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', text)
    seconds = int(duration[1])*3600 + int(duration[2])*60 + float(duration[3]) if duration else 0
    notes = {'duration_seconds': seconds, 'media_kind': 'video'}
    created = re.search(r'creation_time\s*:\s*([^\r\n]+)', text)
    if created:
        try:
            notes.update(date=datetime.fromisoformat(created[1].strip().replace('Z', '+00:00')).date().isoformat(),
                         date_source='video_metadata', precision='day')
        except ValueError:
            pass
    return int(size[1]), int(size[2]), notes


def frame(path, seconds=0, side=512):
    side = max(64, min(2048, int(side)))
    result = run(['-protocol_whitelist', 'file,pipe', '-ss', str(max(0, seconds)), '-i', str(Path(path).resolve()),
                  '-map', '0:v:0', '-an', '-frames:v', '1', '-vf',
                  f'scale={side}:{side}:force_original_aspect_ratio=decrease', '-threads', '1',
                  '-f', 'image2pipe', '-vcodec', 'mjpeg', '-q:v', '3', 'pipe:1'])
    if result.returncode or not result.stdout or len(result.stdout)>16*1024*1024:
        raise ValueError('Fotogramma video non leggibile. Il file resta da catalogare.')
    with Image.open(io.BytesIO(result.stdout)) as image:
        return ImageOps.exif_transpose(image).convert('RGB').copy()


def preview(path, side=384):
    _, _, notes = probe(path)
    return frame(path, notes['duration_seconds']*.1, side)


def storyboard(path, side=512):
    _, _, notes = probe(path)
    duration = notes['duration_seconds']
    moments = [duration*fraction for fraction in (.1, .5, .9)] if duration>1 else [0]
    tile = max(128, int(side))
    sheet = Image.new('RGB', (tile*len(moments), tile+24), '#15151f')
    draw = ImageDraw.Draw(sheet)
    for index, moment in enumerate(moments):
        picture = frame(path, moment, tile)
        sheet.paste(picture, (index*tile+(tile-picture.width)//2, 24+(tile-picture.height)//2))
        draw.text((index*tile+8, 6), f'{moment:.1f} s', fill='white')
    buffer = io.BytesIO()
    sheet.save(buffer, 'JPEG', quality=88)
    return buffer.getvalue(), moments
