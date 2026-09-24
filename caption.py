#!/usr/bin/env python3
"""Offline CPU captions: python caption.py input.mp4 [--style multiword]."""
import argparse
import html
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
from types import SimpleNamespace

# Set before importing any third-party modules. Never fetch a missing model.
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'


def deny_network(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:
        raise RuntimeError('Network access is disabled in caption.py.')


sys.addaudithook(deny_network)


def app_dir():
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def bundled_tool(name):
    candidate = app_dir() / 'ffmpeg' / (name + '.exe' if os.name == 'nt' else name)
    if not candidate.is_file() and not getattr(sys, 'frozen', False):
        candidate = app_dir() / 'vendor' / 'ffmpeg' / candidate.name
    return str(candidate) if candidate.is_file() else name


def edit_transcript_word(payload, segment_index, word_index, text):
    text = text.strip()
    if not text or any(c.isspace() for c in text):
        raise ValueError('Enter one non-empty word (punctuation is allowed).')
    segment = payload['segments'][segment_index]
    original = segment['words'][word_index]['word']
    prefix = original[:len(original) - len(original.lstrip())]
    segment['words'][word_index]['word'] = prefix + text
    segment['text'] = ' '.join(w['word'].strip() for w in segment['words'])


def run(command, cwd=None):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                            encoding='utf-8', errors='replace',
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError('FFmpeg failed:\n' + result.stderr[-6000:])
    return result.stdout + result.stderr


def stamp(seconds, ass=False):
    scale = 100 if ass else 1000
    ticks = max(0, round(seconds * scale))
    whole, fraction = divmod(ticks, scale)
    minutes, second = divmod(whole, 60)
    hour, minute = divmod(minutes, 60)
    if ass:
        return f'{hour}:{minute:02}:{second:02}.{fraction:02}'
    return f'{hour:02}:{minute:02}:{second:02},{fraction:03}'


def clean(text):
    return ' '.join(text.split())


def cues_from_segments(segments):
    """Keep real word boundaries; fall back to segment timing if unavailable."""
    previous_end = 0.0
    for segment in segments:
        words = getattr(segment, 'words', None)
        groups = []
        group = []
        if words:
            for word in words:
                if not clean(word.word):
                    continue
                if group and (len(''.join(w.word for w in group) + word.word) > 76
                              or word.end - group[0].start > 5
                              or word.start - group[-1].end > 0.8):
                    groups.append(group)
                    group = []
                group.append(word)
            if group:
                groups.append(group)
        entries = [(g[0].start, g[-1].end, clean(''.join(w.word for w in g)), g)
                   for g in groups]
        if not entries and clean(segment.text):
            entries = [(segment.start, segment.end, clean(segment.text), [])]
        for start, end, text, word_group in entries:
            start = max(previous_end, float(start), 0.0)
            end = max(start + 0.01, float(end))
            previous_end = end
            yield start, end, text, word_group


def ass_text(text):
    # Prevent recognized text from becoming ASS override tags or escapes.
    return text.replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\n', ' ')


def singleword_cues(segments, fill_gaps=False, min_duration=0):
    """Resolve overlaps on ASS's grid; optionally hold until the next start."""
    words = []
    for segment in segments:
        if clean(segment.text) and not getattr(segment, 'words', None):
            raise ValueError('Single-word mode requires word timestamps. Use --style multiword for segment fallback.')
        for word in getattr(segment, 'words', None) or []:
            text = clean(word.word)
            if not text:
                continue
            if len(text.split()) != 1:
                raise ValueError('A timestamp contains multiple words. Use --style multiword for this transcription.')
            words.append((max(0, round(word.start * 100)),
                          max(0, round(word.end * 100)), text, word))
    words.sort(key=lambda w: w[0])
    for i, (start, end, text, original) in enumerate(words):
        natural_end = max(start + 1, end)
        end = max(start + max(1, math.ceil(min_duration / 10)), natural_end)
        if i + 1 < len(words):
            next_start = words[i + 1][0]
            end = next_start if fill_gaps else min(end, next_start)
        elif fill_gaps:
            # Continuous display's last-word cap remains its normal spoken end.
            end = natural_end
        if end > start:
            yield start / 100, end / 100, text, [original]


def render_cues(segments, style='singleword', fill_gaps=False, min_duration=0):
    if style == 'singleword':
        return list(singleword_cues(segments, fill_gaps, min_duration))
    if fill_gaps or min_duration:
        raise ValueError('Continuous display and minimum duration require singleword mode.')
    return [(round(start * 100) / 100, round(end * 100) / 100, text, words)
            for start, end, text, words in cues_from_segments(segments)]


def karaoke_words(start, words):
    """One shared centisecond schedule for ASS and the interactive preview."""
    cursor = round(start * 100)
    for word in words:
        begin = max(cursor, round(word.start * 100))
        end = max(begin, round(word.end * 100))
        yield begin, end, ass_text(word.word)
        cursor = end


def minimum_duration(value):
    try:
        value = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Minimum duration must be 0 (off) or 100–800 ms.') from exc
    if value != 0 and not 100 <= value <= 800:
        raise argparse.ArgumentTypeError('Minimum duration must be 0 (off) or 100–800 ms.')
    return value


def source_identity(source):
    source = Path(source).resolve()
    stat = source.stat()
    return {'path': str(source), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def unpack_transcript(payload):
    return [SimpleNamespace(start=s['start'], end=s['end'], text=s['text'],
                            source_segment=si,
                            words=[SimpleNamespace(**w, source_ref=(si, wi)) for wi, w in enumerate(s['words'])])
            for si, s in enumerate(payload['segments'])]


def edit_caption_cue(payload, cue, text, style):
    tokens = text.split()
    if not tokens or (style == 'singleword' and len(tokens) != 1):
        raise ValueError('Enter one word.' if style == 'singleword' else 'Enter a non-empty phrase.')
    refs = [w.source_ref for w in cue[3]]
    if not refs:
        # Match by the global cue ordinal, preserving overlap-clipped segment timing.
        segments = unpack_transcript(payload)
        schedule = render_cues(segments, 'multiword')
        offset = 0
        for si, segment in enumerate(segments):
            count = len(list(cues_from_segments([segment])))
            if not segment.words and count and schedule[offset][:3] == cue[:3]:
                payload['segments'][si]['text'] = ' '.join(tokens)
                return
            offset += count
        raise ValueError('Caption no longer matches the transcript. Try again.')
    si, first = refs[0]
    last = refs[-1][1]
    segment = payload['segments'][si]
    old = segment['words'][first:last + 1]
    start, end = old[0]['start'], old[-1]['end']
    replacement = []
    for i, token in enumerate(tokens):
        begin = old[i]['start'] if len(tokens) == len(old) else start + (end-start)*i/len(tokens)
        finish = old[i]['end'] if len(tokens) == len(old) else start + (end-start)*(i+1)/len(tokens)
        replacement.append({'start': begin, 'end': finish, 'word': ' ' + token})
    segment['words'][first:last + 1] = replacement
    segment['text'] = ''.join(w['word'] for w in segment['words']).strip()


def check_model(model_dir):
    missing = [name for name in ('model.bin', 'config.json', 'tokenizer.json')
               if not (model_dir / name).is_file()]
    if missing:
        raise ValueError(f'Incomplete local model: {model_dir}\nMissing: {", ".join(missing)}. '
                         'See README.md for offline provisioning. Nothing will be downloaded.')


def transcribe_local(source, model_dir, ffmpeg, language=None):
    check_model(model_dir)
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError('Install faster-whisper in this Python environment; see README.md.') from exc
    identity = source_identity(source)
    with tempfile.TemporaryDirectory(prefix='caption-', dir=source.parent) as tmp:
        work = Path(tmp)
        print('1/3 Extracting first audio track...', flush=True)
        run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
             '-protocol_whitelist', 'file,pipe', '-i', str(source), '-map', '0:a:0',
             '-vn', '-ac', '1', '-ar', '16000', '-af', 'aresample=async=1:first_pts=0',
             '-c:a', 'pcm_s16le', 'audio.wav'], cwd=work)
        print('2/3 Transcribing locally on CPU (this can take a while)...', flush=True)
        model = WhisperModel(str(model_dir), device='cpu', compute_type='int8', local_files_only=True)
        segments, info = model.transcribe(str(work / 'audio.wav'), language=language,
                                          word_timestamps=True, vad_filter=True,
                                          beam_size=5, condition_on_previous_text=False)
        packed = []
        for segment in segments:
            packed.append({'start': segment.start, 'end': segment.end, 'text': segment.text,
                           'words': [{'start': w.start, 'end': w.end, 'word': w.word}
                                     for w in (getattr(segment, 'words', None) or [])]})
            print(f'  Transcribed through {stamp(segment.end)}', flush=True)
    if source_identity(source) != identity:
        raise ValueError('Video changed during transcription. Please reload it and try again.')
    return {'version': 1, 'source': identity, 'model': str(model_dir),
            'requested_language': language, 'language': info.language, 'segments': packed}


def color(value):
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise argparse.ArgumentTypeError('Color must be #RRGGBB, e.g. "#FFFFFF".')
    return value.upper()


def ass_color(value):
    value = color(value)[1:]
    return '&H00' + value[4:6] + value[2:4] + value[0:2]


def font_name(value):
    if not value.strip() or any(c in value for c in ',\r\n{}\\'):
        raise argparse.ArgumentTypeError('Use a plain font family name without commas or ASS markup.')
    return value.strip()


def percentage(value):
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Position must be a percentage from 0 to 100.') from exc
    if not math.isfinite(number) or not 0 <= number <= 100:
        raise argparse.ArgumentTypeError('Position must be a percentage from 0 to 100.')
    return number


def display_resolution(ffprobe, source):
    result = json.loads(run([ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe',
                             '-select_streams', 'v:0', '-show_entries',
                             'stream=width,height,sample_aspect_ratio:stream_side_data=rotation:stream_tags=rotate',
                             '-of', 'json', str(source)]))
    streams = result.get('streams', [])
    if not streams:
        raise ValueError('Input has no video stream.')
    stream = streams[0]
    width, height = stream['width'], stream['height']
    sar = stream.get('sample_aspect_ratio', '1:1').split(':')
    if len(sar) == 2 and all(x.isdigit() and int(x) > 0 for x in sar):
        width *= int(sar[0]) / int(sar[1])
    rotation = float(stream.get('tags', {}).get('rotate', 0))
    for side in stream.get('side_data_list', []):
        rotation = float(side.get('rotation', rotation))
    if round(rotation) % 180 == 90:
        width, height = height, width
    return max(1, round(width / height * 1920)), 1920


def write_subtitles(cues, srt, ass, *, style='multiword', render_cues=None,
                    font='Arial', font_size=80, text_color=None,
                    outline_color='#000000', resolution=(1080, 1920),
                    position_x=50, position_y=72):
    with srt.open('w', encoding='utf-8', newline='\n') as stream:
        for i, (start, end, text, _) in enumerate(cues, 1):
            wrapped = '\n'.join(textwrap.wrap(text, 40, break_long_words=False,
                                              break_on_hyphens=False))
            stream.write(f'{i}\n{stamp(start)} --> {stamp(end)}\n{html.escape(wrapped)}\n\n')
    primary = ass_color(text_color or ('#FFFFFF' if style == 'singleword' else '#FFFF00'))
    outline = ass_color(outline_color)
    width, height = resolution
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},{primary},&H00FFFFFF,{outline},&H00000000,-1,0,0,0,100,100,0,0,1,4,0,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    with ass.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(header)
        for start, end, text, words in (render_cues if render_cues is not None else cues):
            parts = []
            cursor = round(start * 100)
            for word_start, word_end, word_text in karaoke_words(start, words if style == 'multiword' else []):
                if word_start > cursor:
                    parts.append('{\\k' + str(word_start - cursor) + '}')
                parts.append('{\\k' + str(word_end - word_start) + '}' + word_text)
                cursor = word_end
            content = ''.join(parts) if parts else ass_text(text)
            content = ('{\\an5\\pos(' + str(round(width * position_x / 100)) + ',' + str(round(height * position_y / 100))
                       + ')}') + content
            stream.write(f'Dialogue: 0,{stamp(start, True)},{stamp(end, True)},Default,,0,0,0,,{content}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='Local MP4 video')
    parser.add_argument('--model', type=Path,
                        default=app_dir() / 'models' / 'faster-whisper-small',
                        help='Local CTranslate2 Whisper model directory')
    parser.add_argument('--language', help='Language code, e.g. en; default: auto-detect')
    parser.add_argument('--style', choices=('singleword', 'multiword'), default=None,
                        help='Default: singleword; multiword uses karaoke highlighting')
    parser.add_argument('--highlight', action='store_true', help='Legacy alias for --style multiword')
    parser.add_argument('--fill-gaps', action='store_true',
                        help='Singleword only: hold each word until the next starts; default off')
    parser.add_argument('--min-duration', type=minimum_duration, default=0, metavar='MS',
                        help='Singleword minimum duration: 0 (off, default) or 100–800 ms; clipped at next start')
    parser.add_argument('--transcribe-only', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--transcript-stdin', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--emit-transcript', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--text-color', type=color, help='Quoted #RRGGBB; default white (singleword), yellow (multiword)')
    parser.add_argument('--outline-color', type=color, default='#000000')
    parser.add_argument('--font', type=font_name, default='Arial', help='Installed font family; rendered bold')
    parser.add_argument('--font-size', type=int, default=80, choices=range(16, 241), metavar='16..240',
                        help='Font size on a 1920-high canvas; scales with video (default 80)')
    parser.add_argument('--position-x', type=percentage, default=50, help='Caption center, percent from left (default 50)')
    parser.add_argument('--position-y', type=percentage, default=72, help='Caption center, percent from top (default 72)')
    parser.add_argument('--crf', type=int, default=18, choices=range(0, 52), metavar='0..51')
    parser.add_argument('--ffmpeg', default=bundled_tool('ffmpeg'), help='FFmpeg executable name or path')
    parser.add_argument('--ffprobe', help='Optional FFprobe path; otherwise located beside FFmpeg or on PATH')
    args = parser.parse_args()
    if args.highlight and args.style == 'singleword':
        parser.error('--highlight conflicts with --style singleword')
    args.style = args.style or ('multiword' if args.highlight else 'singleword')
    if args.fill_gaps and args.style != 'singleword':
        parser.error('--fill-gaps requires --style singleword; it conflicts with --style multiword and --highlight')
    if args.min_duration and args.style != 'singleword':
        parser.error('--min-duration requires --style singleword; it conflicts with --style multiword and --highlight')
    source = args.input.expanduser().resolve()
    model_dir = args.model.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != '.mp4':
        raise ValueError('Input must be an existing local .mp4 file.')
    payload = None
    if args.transcript_stdin:
        payload = json.load(sys.stdin)
        if (payload.get('version') != 1 or payload.get('source') != source_identity(source)
                or payload.get('model') != str(model_dir)
                or payload.get('requested_language') != args.language):
            raise ValueError('Cached transcription does not match this video/model/language. Preview again.')
    else:
        check_model(model_dir)
    ffmpeg = shutil.which(args.ffmpeg)
    if not ffmpeg:
        raise ValueError('FFmpeg was not found. Install it separately or use --ffmpeg PATH.')
    if args.transcribe_only:
        payload = payload if payload is not None else transcribe_local(source, model_dir, ffmpeg, args.language)
        print('__CAPTION_TRANSCRIPT__' + json.dumps(payload, ensure_ascii=True), flush=True)
        return
    sibling = Path(ffmpeg).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
    ffprobe = shutil.which(args.ffprobe) if args.ffprobe else (str(sibling) if sibling.is_file() else shutil.which('ffprobe'))
    if not ffprobe:
        raise ValueError('FFprobe was not found. Install the full FFmpeg distribution or use --ffprobe PATH.')
    resolution = display_resolution(ffprobe, source)
    filters = run([ffmpeg, '-hide_banner', '-filters'])
    encoders = run([ffmpeg, '-hide_banner', '-encoders'])
    needed_filter = 'ass'
    if not any(len(line.split()) > 1 and line.split()[1] == needed_filter
               for line in filters.splitlines()):
        raise ValueError(f'FFmpeg needs the {needed_filter} filter (libass support).')
    if 'libx264' not in encoders:
        raise ValueError('FFmpeg needs the libx264 encoder.')
    output = source.with_name(source.stem + '_captioned.mp4')
    srt = source.with_suffix('.srt')
    ass = source.with_suffix('.ass')
    destinations = [output, srt, ass]
    for path in destinations:
        if path.exists():
            raise ValueError(f'Refusing to overwrite: {path}. Move or rename it first.')
    # Work beside the source so completed video promotion stays on one filesystem.
    with tempfile.TemporaryDirectory(prefix='caption-', dir=source.parent) as tmp:
        work = Path(tmp)
        common = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n']
        if payload is None:
            payload = transcribe_local(source, model_dir, ffmpeg, args.language)
        else:
            print('Reusing cached transcription; skipping audio extraction and Whisper.', flush=True)
        if args.emit_transcript:
            print('__CAPTION_TRANSCRIPT__' + json.dumps(payload, ensure_ascii=True), flush=True)
        transcript = unpack_transcript(payload)
        cues = list(cues_from_segments(transcript))
        rendered = render_cues(transcript, args.style, args.fill_gaps, args.min_duration)
        print(f'Language: {payload["language"]}; {len(cues)} caption cues.', flush=True)
        write_subtitles(cues, work / 'captions.srt', work / 'captions.ass', style=args.style,
                        render_cues=rendered, font=args.font, font_size=args.font_size,
                        text_color=args.text_color, outline_color=args.outline_color,
                        resolution=resolution, position_x=args.position_x, position_y=args.position_y)
        # Preserve the raw transcript even if encoding fails.
        with srt.open('xb') as target:
            target.write((work / 'captions.srt').read_bytes())
        with ass.open('xb') as target:
            target.write((work / 'captions.ass').read_bytes())
        print('3/3 Encoding captioned video...', flush=True)
        command = common + ['-protocol_whitelist', 'file,pipe', '-i', str(source),
                            '-map', '0:v:0', '-map', '0:a?', '-map_metadata', '0']
        if rendered:
            command += ['-vf', 'ass=filename=captions.ass']
        else:
            print('No speech detected; saving an empty SRT and an uncaptioned copy.')
        command += ['-c:v', 'libx264', '-preset', 'slow', '-crf', str(args.crf),
                    '-c:a', 'copy', '-movflags', '+faststart', 'encoded.mp4']
        run(command, cwd=work)
        # Exclusive creation prevents clobbering a file created during transcription.
        with output.open('xb') as target:
            try:
                with (work / 'encoded.mp4').open('rb') as encoded:
                    shutil.copyfileobj(encoded, target)
            except BaseException:
                target.close()
                output.unlink(missing_ok=True)
                raise
    print(f'Done:\n  {output}\n  {srt}\n  {ass}')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nCancelled.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
