#!/usr/bin/env python3
"""Small offline front end for caption.py. Launch with: python gui.py"""
import os
import math
import bisect
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import copy

# In a frozen build, Tcl/Tk data is carried in the application bundle. Set
# these before importing tkinter so the extension initializes with the right
# library roots.
if getattr(sys, 'frozen', False):
    _bundle_root = Path(sys.executable).parent
    os.environ['TCL_LIBRARY'] = str(_bundle_root / 'lib' / 'tcl8.6')
    os.environ['TK_LIBRARY'] = str(_bundle_root / 'lib' / 'tk8.6')

import tkinter as tk
from tkinter import colorchooser, filedialog, font, messagebox, scrolledtext, ttk

# Import normally so PyInstaller can collect caption.py into its archive.
# Running `python gui.py` also resolves this sibling module through sys.path.
import caption as pipeline


def pipeline_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--caption-worker']
    return [sys.executable, '-u', str(Path(__file__).with_name('caption.py'))]


def model_path(value):
    return (Path(value).expanduser() if value.strip() else
            pipeline.app_dir() / 'models' / 'faster-whisper-small').resolve()


def cache_matches(payload, source, model):
    if payload is None:
        return False
    try:
        return (payload['source'] == pipeline.source_identity(source)
                and payload['model'] == str(model_path(model))
                and payload['requested_language'] is None)
    except (OSError, KeyError, ValueError):
        return False


def caption_at(cues, starts, seconds, style, color):
    """Half-open intervals match ASS: old text disappears at the next start."""
    index = bisect.bisect_right(starts, seconds) - 1
    if index < 0 or seconds >= cues[index][1]:
        return []
    start, end, text, words = cues[index]
    if style == 'multiword' and words:
        return [(word, color if seconds >= begin / 100 else '#FFFFFF')
                for begin, finish, word in pipeline.karaoke_words(start, words)]
    return [(pipeline.ass_text(text), color)]


def build_command(source, style, family, size, text_color, outline_color, model='',
                  position_x=50, position_y=72, fill_gaps=False, min_duration=0):
    if fill_gaps and style != 'singleword':
        raise ValueError('Continuous display is only available in singleword mode.')
    min_duration = pipeline.minimum_duration(str(min_duration))
    if min_duration and style != 'singleword':
        raise ValueError('Minimum duration is only available in singleword mode.')
    command = pipeline_command() + [
               str(source), '--style', style, '--font', family, '--font-size', str(size),
               '--text-color', text_color, '--outline-color', outline_color,
               '--position-x', str(position_x), '--position-y', str(position_y)]
    if model.strip():
        command += ['--model', model]
    if fill_gaps:
        command.append('--fill-gaps')
    if min_duration:
        command += ['--min-duration', str(min_duration)]
    return command


def fit_frame(width, height, canvas_width, canvas_height):
    scale = min(max(1, canvas_width) / width, max(1, canvas_height) / height)
    w, h = max(1, round(width * scale)), max(1, round(height * scale))
    return (canvas_width - w) / 2, (canvas_height - h) / 2, w, h


def frame_percent(x, y, rect):
    left, top, width, height = rect
    return (max(0, min(100, (x - left) * 100 / width)),
            max(0, min(100, (y - top) * 100 / height)))


def resized_font(size, initial_distance, current_distance):
    return max(16, min(240, round(size * current_distance / max(1, initial_distance))))


def clock_text(seconds):
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}'


class VideoPreview(ttk.Frame):
    """OpenCV decodes local frames; Tk draws images/text without Pillow."""
    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        self.capture = None
        self.cv = None
        self.frame = None
        self.photo = None
        self.rect = None
        self.handles = []
        self.drag = None
        self.playing = False
        self.audio_process = None
        self.editor = None
        self.timer = None
        self.current = 0
        self.loaded_source = None
        self.current_seconds = 0
        self.cues = None
        self.cue_starts = []
        self.count = 0
        self.fps = 0
        self.sar = 1
        self.position_x, self.position_y = 50.0, 72.0
        self.seek_value = tk.DoubleVar(value=0)
        self.sample = tk.StringVar(value='Caption')
        self.readout = tk.StringVar()
        self.time_label = tk.StringVar(value='00:00:00 / 00:00:00')
        ttk.Label(self, text='Live preview', font=('Arial', 15, 'bold')).pack(anchor='w')
        self.canvas = tk.Canvas(self, bg='#17191E', width=440, height=480, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, pady=8)
        self.canvas.create_text(220, 200, text='Choose a local MP4 to preview', fill='white', tags='placeholder')
        controls = ttk.Frame(self)
        controls.pack(fill='x')
        self.play_button = ttk.Button(controls, text='Play', state='disabled', command=self.toggle)
        self.play_button.pack(side='left')
        self.seek = ttk.Scale(controls, from_=0, to=1, variable=self.seek_value, command=self.scrub, state='disabled')
        self.seek.pack(side='left', fill='x', expand=True, padx=8)
        ttk.Label(self, textvariable=self.time_label).pack(anchor='w', pady=4)
        sample_row = ttk.Frame(self)
        sample_row.pack(fill='x')
        ttk.Label(sample_row, text='Sample text: ').pack(side='left')
        ttk.Entry(sample_row, textvariable=self.sample).pack(side='left', fill='x', expand=True)
        ttk.Label(self, textvariable=self.readout).pack(anchor='w', pady=6)
        ttk.Label(self, text='Drag the caption to move it; drag a corner to resize.\nClick Preview Captions for real text and timing. Playback includes audio.',
                  wraplength=420).pack(anchor='w')
        ttk.Button(self, text='Reset placement and size', command=self.reset).pack(anchor='w', pady=6)
        self.canvas.bind('<Configure>', lambda event: self.draw_frame())
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<Double-Button-1>', self.edit_caption)
        self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', lambda event: setattr(self, 'drag', None))
        self.sample.trace_add('write', self.draw_overlay)
        app.size.trace_add('write', self.draw_overlay)
        app.family.trace_add('write', self.draw_overlay)
        self.draw_overlay()

    def load(self, path):
        self.release()
        self.frame = None
        self.rect = None
        self.canvas.delete('all')
        try:
            # Local existing MP4 only; never pass URLs/devices/playlists to OpenCV.
            source = Path(path).expanduser().resolve()
            if not source.is_file() or source.suffix.lower() != '.mp4':
                raise ValueError('Choose an existing local MP4 file.')
            self.loaded_source = str(source)
            if self.cv is None:
                os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'protocol_whitelist;file,pipe'
                import cv2
                self.cv = cv2
            cv = self.cv
            self.capture = cv.VideoCapture(str(source), cv.CAP_FFMPEG)
            if not self.capture.isOpened():
                raise ValueError('OpenCV could not open this MP4. Its codec may not be supported.')
            self.capture.set(cv.CAP_PROP_ORIENTATION_AUTO, 1)
            self.fps = self.capture.get(cv.CAP_PROP_FPS)
            count = self.capture.get(cv.CAP_PROP_FRAME_COUNT)
            if not math.isfinite(self.fps) or self.fps <= 0 or not math.isfinite(count) or count < 1:
                raise ValueError('The video has no usable frame-rate/frame-count metadata for preview.')
            self.count = round(count)
            numerator = self.capture.get(cv.CAP_PROP_SAR_NUM)
            denominator = self.capture.get(cv.CAP_PROP_SAR_DEN)
            self.sar = numerator / denominator if numerator > 0 and denominator > 0 else 1
            rotation = self.capture.get(cv.CAP_PROP_ORIENTATION_META)
            if math.isfinite(rotation) and round(rotation) % 180 == 90:
                self.sar = 1 / self.sar
            self.seek.configure(to=max(1, self.count - 1), state='normal')
            self.play_button.configure(state='normal')
            if not self.read_frame(0):
                raise ValueError('The first video frame could not be decoded.')
        except Exception as exc:
            self.release()
            self.canvas.create_text(20, 30, anchor='nw', width=380, fill='white',
                                    text='Preview unavailable. See the output box for details.')
            if isinstance(exc, ImportError):
                self.app.append('Preview needs OpenCV: python -m pip install opencv-python\n')
            else:
                self.app.append(f'Preview error: {exc}\n')

    def read_frame(self, index):
        index = max(0, min(self.count - 1, int(index)))
        if index != self.current + 1 or self.frame is None:
            self.capture.set(self.cv.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.capture.read()
        if not ok:
            self.pause()
            return False
        self.current, self.frame = index, frame
        timestamp = self.capture.get(self.cv.CAP_PROP_POS_MSEC) / 1000
        self.current_seconds = timestamp if math.isfinite(timestamp) and (timestamp > 0 or index == 0) else index / self.fps
        # Setting the variable (rather than Scale.set) avoids a seek callback.
        self.seek_value.set(index)
        self.time_label.set(f'{clock_text(self.current_seconds)} / {clock_text(self.count / self.fps)}')
        self.draw_frame()
        return True

    def draw_frame(self):
        if self.frame is None:
            return
        h, w = self.frame.shape[:2]
        self.rect = fit_frame(w * self.sar, h, self.canvas.winfo_width(), self.canvas.winfo_height())
        x, y, width, height = self.rect
        scaled = self.cv.resize(self.frame, (width, height), interpolation=self.cv.INTER_AREA)
        rgb = self.cv.cvtColor(scaled, self.cv.COLOR_BGR2RGB)
        ppm = f'P6\n{width} {height}\n255\n'.encode('ascii') + rgb.tobytes()
        self.photo = tk.PhotoImage(master=self.canvas, data=ppm, format='PPM')
        self.canvas.delete('video')
        self.canvas.create_image(x, y, anchor='nw', image=self.photo, tags='video')
        self.canvas.tag_lower('video')
        self.draw_overlay()

    def draw_overlay(self, *unused):
        try:
            size = self.app.size.get()
        except (ValueError, tk.TclError):
            return
        mode = 'Real captions' if self.cues is not None else 'Sample'
        self.readout.set(f'{mode} • Position: {self.position_x:.1f}% × {self.position_y:.1f}%   Font size: {size}')
        self.canvas.delete('caption')
        self.handles = []
        if self.rect is None:
            return
        left, top, width, height = self.rect
        x = left + width * self.position_x / 100
        y = top + height * self.position_y / 100
        pixels = max(1, round(max(16, min(240, size)) * height / 1920))
        self.caption_font = font.Font(root=self, family=self.app.family.get(), size=-pixels, weight='bold')
        if self.cues is None:
            fragments = [(self.sample.get() or 'Caption', self.app.text_color)]
        else:
            fragments = caption_at(self.cues, self.cue_starts, self.current_seconds,
                                   self.app.style.get(), self.app.text_color)
        if not fragments:
            return
        # Word wrapping and per-word colors approximate libass typography while
        # using the exact shared cue and karaoke timing schedule.
        lines = [[]]
        line_width = 0
        available = max(1, width - 80 * height / 1920)
        for text, color in fragments:
            for token in pipeline.re.findall(r'\s+|\S+', text):
                measured = self.caption_font.measure(token)
                if line_width + measured > available and lines[-1] and not token.isspace():
                    lines.append([])
                    line_width = 0
                if not lines[-1] and token.isspace():
                    continue
                lines[-1].append((token, color, measured))
                line_width += measured
        line_height = self.caption_font.metrics('linespace')
        top_text = y - len(lines) * line_height / 2
        stroke = max(1, round(4 * height / 1920))
        for row, line in enumerate(lines):
            cursor = x - sum(piece[2] for piece in line) / 2
            for text, color, measured in line:
                ty = top_text + row * line_height
                for dx, dy in ((-stroke, 0), (stroke, 0), (0, -stroke), (0, stroke),
                               (-stroke, -stroke), (-stroke, stroke), (stroke, -stroke), (stroke, stroke)):
                    self.canvas.create_text(cursor+dx, ty+dy, anchor='nw', text=text,
                                            font=self.caption_font, fill=self.app.outline_color, tags='caption')
                self.canvas.create_text(cursor, ty, anchor='nw', text=text, font=self.caption_font,
                                        fill=color, tags='caption')
                cursor += measured
        bounds = self.canvas.bbox('caption')
        if bounds:
            x1, y1, x2, y2 = bounds
            self.bounds = (x1 - 7, y1 - 7, x2 + 7, y2 + 7)
            x1, y1, x2, y2 = self.bounds
            self.canvas.create_rectangle(*self.bounds, outline='#66C9FF', dash=(3, 3), tags='caption')
            self.handles = [(x1, y1), (x1, y2), (x2, y1), (x2, y2)]
            for hx, hy in self.handles:
                self.canvas.create_rectangle(hx-5, hy-5, hx+5, hy+5, fill='#66C9FF', outline='white', tags='caption')

    def edit_caption(self, event):
        if self.editor is not None:
            return 'break'
        if self.app.running or self.app.current_cache() is None or not self.cues:
            self.app.status.set('Finish Preview Captions first, then double-click a visible caption.')
            return 'break'
        bounds = self.canvas.bbox('caption')
        if not bounds or not (bounds[0] <= event.x <= bounds[2] and bounds[1] <= event.y <= bounds[3]):
            return 'break'
        index = bisect.bisect_right(self.cue_starts, self.current_seconds) - 1
        if index < 0 or self.current_seconds >= self.cues[index][1]:
            return 'break'
        self.pause()
        self.drag = None
        self.edit_cue = self.cues[index]
        self.edit_payload = self.app.cache
        self.edit_style = self.app.style.get()
        self.editor = tk.Entry(self.canvas, font=self.caption_font, justify='center',
                               fg=self.app.text_color, bg='#17191E', insertbackground='white')
        self.editor.insert(0, self.edit_cue[2])
        self.editor.select_range(0, 'end')
        x1, y1, x2, y2 = bounds
        width = min(max(100, x2-x1), self.canvas.winfo_width())
        x = max(0, min((x1+x2-width)/2, self.canvas.winfo_width()-width))
        self.editor.place(x=x, y=max(0, y1), width=width, height=max(26, y2-y1))
        self.editor.lift()
        editor = self.editor
        self.after_idle(lambda: editor.focus_set() if self.editor is editor else None)
        editor.bind('<Return>', self.commit_edit)
        editor.bind('<FocusOut>', self.commit_edit)
        editor.bind('<Escape>', self.cancel_edit)
        self.app.status.set('Edit caption here. Enter or click away saves; Escape cancels.')
        return 'break'

    def cancel_edit(self, event=None):
        editor, self.editor = self.editor, None
        if editor is not None:
            editor.destroy()
        return 'break'

    def commit_edit(self, event=None):
        if self.editor is None:
            return True
        if self.app.current_cache() is not self.edit_payload:
            self.cancel_edit()
            return True
        try:
            pipeline.edit_caption_cue(self.edit_payload, self.edit_cue, self.editor.get(), self.edit_style)
        except ValueError as exc:
            self.app.status.set(str(exc))
            return False
        self.cancel_edit()
        self.app.recompute_preview()
        self.app.status.set('Caption saved in the preview/export cache.')
        return True

    def press(self, event):
        if self.editor is not None:
            self.commit_edit()
            return
        if self.rect is None or not self.handles:
            return
        left, top, width, height = self.rect
        center = (left + width * self.position_x / 100, top + height * self.position_y / 100)
        if any(abs(event.x - x) <= 8 and abs(event.y - y) <= 8 for x, y in self.handles):
            self.drag = ('resize', center, math.hypot(event.x-center[0], event.y-center[1]), self.app.size.get())
        elif self.bounds[0] <= event.x <= self.bounds[2] and self.bounds[1] <= event.y <= self.bounds[3]:
            self.drag = ('move', event.x-center[0], event.y-center[1])

    def motion(self, event):
        if self.drag is None or self.rect is None:
            return
        if self.drag[0] == 'move':
            self.position_x, self.position_y = frame_percent(event.x-self.drag[1], event.y-self.drag[2], self.rect)
            self.draw_overlay()
        else:
            _, center, distance, size = self.drag
            current = math.hypot(event.x-center[0], event.y-center[1])
            self.app.size.set(resized_font(size, distance, current))

    def reset(self):
        self.position_x, self.position_y = 50.0, 72.0
        self.app.size.set(80)
        self.draw_overlay()

    def scrub(self, value):
        if not self.commit_edit():
            return
        if self.capture is None:
            return
        self.pause()
        if not self.read_frame(round(float(value))):
            self.app.append('Preview could not decode the selected frame.\n')

    def toggle(self):
        if not self.commit_edit():
            return
        if self.playing:
            self.pause()
        elif self.capture is not None:
            if self.current >= self.count - 1 and not self.read_frame(0):
                return
            self.playing = True
            self.start_audio()
            self.play_button.configure(text='Pause')
            self.origin_frame, self.origin_time = self.current, time.monotonic()
            self.timer = self.after(max(1, round(1000 / self.fps)), self.tick)

    def tick(self):
        self.timer = None
        if not self.playing:
            return
        elapsed = time.monotonic() - self.origin_time
        target = min(self.count - 1, self.origin_frame + int(elapsed * self.fps))
        if target > self.current and not self.read_frame(target):
            self.app.append('Preview stopped: frame decoding failed.\n')
            return
        if self.current >= self.count - 1:
            self.pause()
            return
        deadline = self.origin_time + (self.current - self.origin_frame + 1) / self.fps
        self.timer = self.after(max(1, math.ceil((deadline - time.monotonic()) * 1000)), self.tick)

    def pause(self):
        self.stop_audio()
        self.playing = False
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        self.play_button.configure(text='Play')

    def start_audio(self):
        self.stop_audio()
        try:
            self.audio_process = subprocess.Popen(
                [pipeline.bundled_tool('ffplay'), '-nodisp', '-autoexit', '-vn',
                 '-loglevel', 'error', '-ss', str(self.current_seconds),
                 '-protocol_whitelist', 'file,pipe', '-i', self.loaded_source],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except OSError as exc:
            self.app.append(f'Preview audio unavailable: {exc}\n')

    def stop_audio(self):
        process, self.audio_process = self.audio_process, None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    process.kill()
            process.wait()

    def release(self):
        self.cancel_edit()
        self.pause()
        self.drag = None
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        self.play_button.configure(state='disabled')
        self.seek.configure(state='disabled')


class CaptionApp:
    def __init__(self, root):
        self.root = root
        root.title('Offline Video Captions')
        root.geometry('1220x780')
        root.minsize(1000, 650)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.events = queue.Queue()
        self.running = False
        self.cache = None
        self.cache_epoch = 0
        self.job_kind = 'export'
        self.job_epoch = 0
        self.output = None
        self.source = tk.StringVar()
        self.model = tk.StringVar()
        self.style = tk.StringVar(value='singleword')
        self.fill_gaps = tk.BooleanVar(value=False)
        self.min_enabled = tk.BooleanVar(value=False)
        self.min_ms = tk.IntVar(value=250)
        self.size = tk.IntVar(value=80)
        self.text_color = '#FFFFFF'
        self.outline_color = '#000000'
        families = sorted(set(font.families(root)), key=str.casefold)
        preferred = next((name for name in ('Montserrat', 'Arial', 'DejaVu Sans', 'Liberation Sans', 'Helvetica')
                          if name in families), font.nametofont('TkDefaultFont').actual('family'))
        self.family = tk.StringVar(value=preferred)
        self.status = tk.StringVar(value='Choose a video to begin. Processing stays on this computer.')
        panes = ttk.Panedwindow(root, orient='horizontal')
        panes.pack(fill='both', expand=True)
        body = ttk.Frame(panes, padding=16)
        panes.add(body, weight=1)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text='Offline Video Captions', font=('Arial', 18, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 14))
        ttk.Label(body, text='MP4 video').grid(row=1, column=0, sticky='w')
        source_entry = ttk.Entry(body, textvariable=self.source)
        source_entry.grid(row=1, column=1, sticky='ew', padx=8)
        source_entry.bind('<Return>', lambda event: self.preview.load(self.source.get()))
        ttk.Button(body, text='Choose video…', command=self.pick_video).grid(row=1, column=2)
        ttk.Label(body, text='Local model (optional)').grid(row=2, column=0, sticky='w', pady=8)
        ttk.Entry(body, textvariable=self.model).grid(row=2, column=1, sticky='ew', padx=8)
        ttk.Button(body, text='Choose folder…', command=self.pick_model).grid(row=2, column=2)
        ttk.Label(body, text='Caption mode').grid(row=3, column=0, sticky='w')
        ttk.Combobox(body, textvariable=self.style, values=('singleword', 'multiword'), state='readonly').grid(row=3, column=1, sticky='ew', padx=8, pady=6)
        self.fill_gaps_check = ttk.Checkbutton(body, text='Continuous display', variable=self.fill_gaps)
        self.fill_gaps_check.grid(row=3, column=2, sticky='w')
        self.style.trace_add('write', self.update_fill_gaps)
        ttk.Label(body, text='Font (bold)').grid(row=4, column=0, sticky='w')
        ttk.Combobox(body, textvariable=self.family, values=families, state='readonly').grid(row=4, column=1, sticky='ew', padx=8, pady=6)
        ttk.Label(body, text='Font size').grid(row=5, column=0, sticky='w')
        tk.Scale(body, from_=16, to=240, orient='horizontal', variable=self.size, highlightthickness=0).grid(row=5, column=1, sticky='ew', padx=8)
        ttk.Spinbox(body, from_=16, to=240, textvariable=self.size, width=6).grid(row=5, column=2)
        ttk.Label(body, text='Size scales from a 1920-pixel-high canvas; default 80 suits vertical video.', wraplength=460).grid(row=6, column=0, columnspan=3, sticky='w', pady=(0, 10))
        colors = ttk.Frame(body)
        colors.grid(row=7, column=0, columnspan=3, sticky='w')
        self.text_button = tk.Button(colors, text='Text: #FFFFFF', bg=self.text_color, fg='black', command=lambda: self.pick_color('text'))
        self.text_button.pack(side='left', padx=(0, 12))
        self.outline_button = tk.Button(colors, text='Outline: #000000', bg=self.outline_color, fg='white', command=lambda: self.pick_color('outline'))
        self.outline_button.pack(side='left')
        actions = ttk.Frame(body)
        actions.grid(row=8, column=0, columnspan=3, sticky='ew', pady=8)
        self.min_check = ttk.Checkbutton(actions, text='Minimum word duration (ms)', variable=self.min_enabled,
                                         command=self.recompute_preview)
        self.min_check.grid(row=0, column=0, columnspan=2, sticky='w')
        self.min_slider = tk.Scale(actions, from_=100, to=800, resolution=10, orient='horizontal',
                                   variable=self.min_ms, highlightthickness=0)
        self.min_slider.grid(row=1, column=0, sticky='ew')
        self.min_input = ttk.Spinbox(actions, from_=100, to=800, increment=10, textvariable=self.min_ms, width=6)
        self.min_input.grid(row=1, column=1, padx=8)
        actions.columnconfigure(0, weight=1)
        self.preview_button = ttk.Button(actions, text='Preview Captions', command=self.preview_captions)
        self.preview_button.grid(row=2, column=0, sticky='ew', pady=6)
        self.generate = ttk.Button(actions, text='Generate Captions', command=self.start)
        self.generate.grid(row=2, column=1, sticky='ew', padx=8, pady=6)
        self.log = scrolledtext.ScrolledText(body, height=8, wrap='word', state='disabled')
        self.log.grid(row=9, column=0, columnspan=3, sticky='nsew')
        body.rowconfigure(9, weight=1)
        ttk.Label(body, textvariable=self.status, wraplength=460).grid(row=10, column=0, columnspan=3, sticky='w', pady=10)
        self.open_button = ttk.Button(body, text='Open containing folder', state='disabled', command=self.open_folder)
        self.open_button.grid(row=11, column=0, columnspan=3, sticky='w')
        self.preview = VideoPreview(panes, self)
        panes.add(self.preview, weight=1)
        self.source.trace_add('write', self.source_changed)
        self.model.trace_add('write', self.invalidate_cache)
        for variable in (self.style, self.fill_gaps, self.min_ms, self.min_enabled):
            variable.trace_add('write', self.recompute_preview)
        root.after(100, self.poll)

    def update_fill_gaps(self, *unused):
        if self.style.get() == 'singleword':
            self.fill_gaps_check.configure(state='normal')
        else:
            self.fill_gaps.set(False)
            self.fill_gaps_check.configure(state='disabled')
            self.min_enabled.set(False)
        state = 'normal' if self.style.get() == 'singleword' else 'disabled'
        for control in (self.min_check, self.min_slider, self.min_input):
            control.configure(state=state)

    def minimum_value(self):
        if not self.min_enabled.get() or self.style.get() != 'singleword':
            return 0
        value = pipeline.minimum_duration(str(self.min_ms.get()))
        if value == 0:
            raise ValueError('Enabled minimum duration must be 100–800 ms; uncheck it to disable.')
        return value

    def invalidate_cache(self, *unused):
        self.preview.cancel_edit()
        self.cache = None
        self.cache_epoch += 1
        self.preview.cues = None
        self.preview.cue_starts = []
        self.preview.draw_overlay()

    def source_changed(self, *unused):
        if cache_matches(self.cache, self.source.get(), self.model.get()):
            return
        self.invalidate_cache()
        self.preview.release()
        self.preview.frame = None
        self.preview.rect = None
        self.preview.loaded_source = None
        self.preview.canvas.delete('all')

    def current_cache(self):
        if cache_matches(self.cache, self.source.get(), self.model.get()):
            return self.cache
        if self.cache is not None:
            self.invalidate_cache()
        return None

    def recompute_preview(self, *unused):
        if not hasattr(self, 'preview'):
            return
        cached = self.current_cache()
        if cached is not None:
            try:
                cues = pipeline.render_cues(pipeline.unpack_transcript(cached), self.style.get(),
                                            self.fill_gaps.get() if self.style.get() == 'singleword' else False,
                                            self.minimum_value())
                self.preview.cues = cues
                self.preview.cue_starts = [cue[0] for cue in cues]
            except (ValueError, tk.TclError, pipeline.argparse.ArgumentTypeError) as exc:
                self.preview.cues = []
                self.preview.cue_starts = []
                self.status.set(f'Preview settings: {exc}')
        self.preview.draw_overlay()

    def preview_captions(self):
        if self.running:
            return
        source = Path(self.source.get()).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() != '.mp4':
            messagebox.showerror('Choose a video', 'Select an existing local .mp4 file.')
            return
        if self.preview.loaded_source != str(source) or self.preview.capture is None:
            self.preview.load(source)
        if self.current_cache() is not None:
            self.recompute_preview()
            self.status.set('Using cached captions. Play or scrub to preview; edits update immediately.')
            return
        command = pipeline_command() + [
                   str(source), '--transcribe-only', '--model', str(model_path(self.model.get()))]
        self.begin_job('preview')
        self.append('\nTranscribing once for the real caption preview…\n')
        threading.Thread(target=self.worker, args=(command, None, self.job_epoch), daemon=True).start()

    def begin_job(self, kind):
        self.job_kind = kind
        self.job_epoch = self.cache_epoch
        self.running = True
        self.preview.pause()
        self.generate.configure(state='disabled')
        self.preview_button.configure(state='disabled')
        self.status.set('Transcribing for preview…' if kind == 'preview' else 'Exporting… Settings captured when you started.')

    def pick_video(self):
        chosen = filedialog.askopenfilename(title='Choose a local MP4', filetypes=[('MP4 videos', '*.mp4')])
        if chosen:
            self.source.set(chosen)
            self.preview.load(chosen)

    def pick_model(self):
        chosen = filedialog.askdirectory(title='Choose local faster-whisper model folder')
        if chosen:
            self.model.set(chosen)

    def pick_color(self, which):
        current = self.text_color if which == 'text' else self.outline_color
        _, chosen = colorchooser.askcolor(color=current, title=f'Choose {which} color')
        if chosen:
            chosen = chosen.upper()
            setattr(self, which + '_color', chosen)
            button = self.text_button if which == 'text' else self.outline_button
            rgb = [int(chosen[i:i+2], 16) for i in (1, 3, 5)]
            foreground = 'black' if sum(rgb) > 380 else 'white'
            button.configure(text=f'{which.title()}: {chosen}', bg=chosen, fg=foreground)
            self.preview.draw_overlay()

    def append(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text)
        self.log.see('end')
        self.log.configure(state='disabled')

    def start(self):
        if not self.preview.commit_edit():
            return
        if self.running:
            return
        source = Path(self.source.get()).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() != '.mp4':
            messagebox.showerror('Choose a video', 'Select an existing local .mp4 file.')
            return
        try:
            size = self.size.get()
            if not 16 <= size <= 240:
                raise ValueError()
            minimum = self.minimum_value()
        except (ValueError, tk.TclError, pipeline.argparse.ArgumentTypeError):
            messagebox.showerror('Caption settings', 'Font size must be 16–240. Enabled minimum duration must be 100–800 ms.')
            return
        command = build_command(source, self.style.get(), self.family.get(), size,
                                self.text_color, self.outline_color, self.model.get(),
                                self.preview.position_x, self.preview.position_y,
                                fill_gaps=self.fill_gaps.get(), min_duration=minimum)
        cached = copy.deepcopy(self.current_cache())
        command.append('--emit-transcript')
        if cached is not None:
            command.append('--transcript-stdin')
        self.output = source.with_name(source.stem + '_captioned.mp4')
        self.begin_job('export')
        self.open_button.configure(state='disabled')
        self.append('\nStarting local caption generation…\n')
        threading.Thread(target=self.worker, args=(command, cached, self.job_epoch), daemon=True).start()

    def worker(self, command, cached=None, epoch=None):
        # Worker never touches Tk widgets. The main thread consumes the queue.
        try:
            env = dict(os.environ, PYTHONIOENCODING='utf-8', HF_HUB_OFFLINE='1',
                       HF_HUB_DISABLE_TELEMETRY='1', TRANSFORMERS_OFFLINE='1')
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  stdin=subprocess.PIPE if cached is not None else subprocess.DEVNULL,
                                  text=True, encoding='utf-8', errors='replace', env=env,
                                  creationflags=flags) as process:
                if cached is not None:
                    try:
                        json.dump(cached, process.stdin, ensure_ascii=True)
                        process.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass  # Read the child's actual validation error below.
                for line in process.stdout:
                    if line.startswith('__CAPTION_TRANSCRIPT__'):
                        self.events.put(('transcript', (epoch, json.loads(line[len('__CAPTION_TRANSCRIPT__'):]))))
                    else:
                        self.events.put(('line', line))
                self.events.put(('done', process.wait()))
        except Exception as exc:
            self.events.put(('line', f'Error launching caption.py: {exc}\n'))
            self.events.put(('done', 1))

    def poll(self):
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'line':
                self.append(value)
            elif kind == 'transcript':
                epoch, payload = value
                if epoch == self.cache_epoch and cache_matches(payload, self.source.get(), self.model.get()):
                    self.cache = payload
                    self.preview.cancel_edit()
                    self.recompute_preview()
            else:
                self.running = False
                self.generate.configure(state='normal')
                self.preview_button.configure(state='normal')
                if self.job_kind == 'preview':
                    if value == 0 and self.current_cache() is not None:
                        self.status.set('Captions ready. Play/scrub and adjust settings; no more transcription needed.')
                    elif value == 0:
                        self.status.set('Video/model changed; old preview result discarded. Click Preview Captions again.')
                    else:
                        self.status.set('Preview transcription failed. See the output box for details.')
                elif value == 0 and self.output.is_file():
                    self.status.set(f'Done: {self.output}')
                    self.open_button.configure(state='normal')
                else:
                    self.status.set('Generation failed. See the output box for the error and next steps.')
        self.root.after(100, self.poll)

    def open_folder(self):
        if self.output:
            try:
                folder = str(self.output.parent)
                if os.name == 'nt':
                    os.startfile(folder)
                else:
                    subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', folder])
            except OSError as exc:
                messagebox.showerror('Cannot open folder', f'{exc}\n\n{self.output.parent}')

    def close(self):
        self.preview.pause()
        if self.running:
            messagebox.showinfo('Generation is running', 'Please wait for generation to finish before closing this window.')
        else:
            self.preview.release()
            self.root.destroy()


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    if '--caption-worker' in sys.argv:
        sys.argv.remove('--caption-worker')
        pipeline.main()
        sys.exit(0)
    window = tk.Tk()
    CaptionApp(window)
    window.mainloop()
