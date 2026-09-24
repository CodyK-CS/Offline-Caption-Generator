# Offline video captions

Command-line `caption.py` and optional lightweight Tkinter `gui.py`, designed for **Windows 10/11 x64**, also usable on **Ubuntu/Debian x64**. Uses faster-whisper on the CPU with int8 computation. No account, API key, paid service, GPU, or cloud transcription is required.

## Dependencies

- Python 3.11 recommended (64-bit).
- Pip package: `faster-whisper>=1.2,<2`.
- Its direct dependencies, installed automatically by pip: `ctranslate2`, `huggingface-hub`, `tokenizers`, `onnxruntime`, `av` (PyAV), and `tqdm`. Pip also installs their supporting dependencies, such as NumPy and packaging/network client libraries; the exact full resolved list depends on the Python/platform versions. `pip freeze` below records every installed package and version. No Python `ffmpeg` or `ffmpeg-python` package is needed.
- **FFmpeg must be installed separately**, with the `libx264` encoder and `ass` filter (libass). The distribution must also include **ffprobe**, used to determine display dimensions and rotation for caption placement. PyAV's bundled decoding libraries do not supply these command-line programs. FFprobe is found beside FFmpeg or on PATH; `--ffprobe PATH` can override it.
- Optional GUI: `tkinter`, included in the standard Windows Python installer (enable Tcl/Tk). On Ubuntu/Debian install `python3-tk`. The live video preview also requires the pip package `opencv-python` (which installs NumPy automatically). No Pillow package is needed; frames are passed directly to Tk as PPM images. Opening folders on Linux uses the desktop's `xdg-open` (`xdg-utils`).
- Local CTranslate2 Whisper model files. The default is the multilingual `Systran/faster-whisper-small` model in `models/faster-whisper-small` beside `caption.py`. Allow roughly 500 MB for that model, plus Python packages and temporary video/audio files.
- Windows may need the Microsoft Visual C++ 2015–2022 x64 runtime for CTranslate2; an install command is included below. Linux needs a font installed for caption rendering.

**Provisioning versus offline operation:** Software and model files must come from somewhere. The setup commands below download public packages/model weights once, without any key or login. They do not upload videos. If the target machine must never connect, use the separate offline transfer procedure below. `caption.py` itself has no download mode, requires a local model with its tokenizer, enables offline library settings, and blocks Python socket connection attempts. FFmpeg inputs are restricted to local file/pipe protocols.

## Windows setup (PowerShell)

Save `caption.py`, `gui.py`, and this README in the same folder. Open PowerShell there.

```powershell
winget install --exact --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
winget install --exact --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
winget install --exact --id Microsoft.VCRedist.2015+.x64 --accept-package-agreements --accept-source-agreements
```

Reopen PowerShell in that folder so PATH reflects the installations, then:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "faster-whisper>=1.2,<2" opencv-python
.\.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Systran/faster-whisper-small', local_dir='models/faster-whisper-small', token=False)"
.\.venv\Scripts\python.exe -m pip freeze > requirements-lock.txt
ffmpeg -version
.\.venv\Scripts\python.exe caption.py "C:\Videos\input.mp4"
```

For the exact short command `python caption.py input.mp4`, put the virtual environment first on PATH in the current PowerShell session:

```powershell
$env:Path = "$PWD\.venv\Scripts;" + $env:Path
python caption.py input.mp4
```

No activation script or PowerShell execution-policy change is necessary.

## Linux setup (Ubuntu/Debian)

Run in the folder containing `caption.py`:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-tk ffmpeg fonts-dejavu-core xdg-utils
python3 -m venv .venv
source .venv/bin/activate
python -m pip install 'faster-whisper>=1.2,<2' opencv-python
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Systran/faster-whisper-small', local_dir='models/faster-whisper-small', token=False)"
python -m pip freeze > requirements-lock.txt
ffmpeg -version
python caption.py input.mp4
```

Use a supported 64-bit Python version (3.11 recommended); wheel availability can vary on other architectures. Linux fontconfig will substitute an installed font if Arial is unavailable.

## Provision a machine that never connects to the internet

On a connected machine with **the same OS, CPU architecture, and Python version** as the target, use a fresh virtual environment and run:

```text
python -m pip install "faster-whisper>=1.2,<2" opencv-python
python -m pip freeze > requirements-lock.txt
python -m pip download --only-binary=:all: --dest wheelhouse -r requirements-lock.txt
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Systran/faster-whisper-small', local_dir='models/faster-whisper-small', token=False)"
```

Transfer `caption.py`, `gui.py`, `requirements-lock.txt`, `wheelhouse/`, and the entire `models/` directory using removable storage. Also transfer a Python installer with Tcl/Tk, FFmpeg distribution including FFprobe, and the Windows Visual C++ runtime installer if needed. For Ubuntu/Debian, arrange the FFmpeg/Python/Tk/font OS packages and all their dependencies through your distribution's offline installation procedure or an offline package mirror; pip wheels do not contain those system dependencies.

On the offline target, install those system prerequisites from local media, create a virtual environment using the applicable commands above, and run with its Python:

```text
python -m pip install --no-index --find-links=wheelhouse -r requirements-lock.txt
python caption.py input.mp4
```

Do not run the model download command on the offline target. Do not copy the virtual environment itself across machines; install from the transferred wheels.

## Usage and output

```text
python caption.py input.mp4
python caption.py input.mp4 --style singleword
python caption.py input.mp4 --style singleword --fill-gaps
python caption.py input.mp4 --min-duration 250
python caption.py input.mp4 --style multiword
python caption.py input.mp4 --highlight
python caption.py input.mp4 --font "Arial" --font-size 80 --text-color "#FFFFFF" --outline-color "#000000"
python caption.py input.mp4 --language en --crf 16
python caption.py input.mp4 --model "D:/Models/faster-whisper-small"
python caption.py input.mp4 --ffmpeg "C:/Tools/ffmpeg/bin/ffmpeg.exe"
```

For `input.mp4`, the script saves files next to the input:

- `input_captioned.mp4`: captions burned into the image.
- `input.srt`: separate UTF-8 text captions, always saved.
- `input.ass`: always saved; the chosen style is burned into the video from this file.

**Default: `--style singleword`.** Each individual word has its own ASS event using its word start/end, with hard cuts and no animation. Text is bold Arial (or the local font substitute), white with a black four-unit outline, no shadow and no background box. Its default center is at 50% of frame width and 72% of frame height, adjustable in the preview or through position flags. Gaps in speech remain blank. Overlaps are clipped at the next word's start on ASS's 10 ms timing grid; a word with no available interval after rounding is omitted instead of overlapping. No word timings are fabricated: if a speech segment lacks word timestamps, or one timestamp unexpectedly contains multiple space-separated words, the script asks you to use multiword mode.

**`--style multiword`** keeps grouped karaoke captions. `--highlight` remains a backward-compatible alias for this mode; combining it with `--style singleword` is an error. The CLI defaults to yellow highlighting with white upcoming words. `--text-color` changes the highlight color. Grouped cues break around five seconds, 76 characters, or speech pauses, with segment fallback when word timing is unavailable. Highlighting is cumulative within each cue, not an active-word-only effect.

Both styles accept `--font`, `--font-size` (16–240), `--text-color`, `--outline-color`, `--position-x`, and `--position-y`. Positions are percentages from the left/top of the video, from 0 to 100, and refer to the caption center; defaults are 50 and 72. For example: `python caption.py input.mp4 --position-x 40 --position-y 65 --font-size 100`. Quote colors as `"#RRGGBB"`. Font size defaults to 80 on a 1920-pixel-high virtual canvas and scales proportionally with video height; for a 1080×1920 video it is 80. Fonts remain bold. The canvas follows the video's display aspect ratio, including quarter-turn rotation metadata. Fonts must already be installed; none are downloaded. For extreme font sizes/long words, lower the font size to fit the frame.

The separate SRT remains a readable, grouped transcript regardless of rendering style, wrapping near 40 characters. Whisper's text and word timing are estimates and may need human correction.

### Continuous display (singleword only)

The CLI flag `--fill-gaps` and GUI checkbox **Continuous display** control the same setting. Both default to **OFF**.

- **OFF (unchanged):** Each word's ASS cue uses its actual spoken start/end from Whisper, subject to the existing 10 ms rounding and overlap clipping. During any silence or pause between words, no caption is shown.
- **ON:** Each word's cue END is set to the START of the next word instead of its own spoken end. The word stays visible through a pause until the next word appears. The very last word keeps its normal end time; it is not extended to the end of the video. Nothing is added before the first word.

Both modes use the same 10 ms ASS grid and drop a word if it has no available interval before the next word starts. Gap filling never creates overlapping words: overlapping spoken durations are still clipped at the next start. It applies across Whisper segment boundaries as well as within segments. The separate grouped SRT is unchanged.

`--fill-gaps` combined with `--style multiword` or its legacy alias `--highlight` is an error, consistent with existing style conflict handling. In the GUI, switching to multiword clears and disables the checkbox; switching back enables it in the OFF state. The checkbox affects both exported captions and the real caption preview after transcription. Before transcription, the static sample has no speech timing. No new dependencies or network access are introduced.

## Launch the GUI

With the same environment used for the CLI:

```text
python gui.py
```

Or without activation on Windows:

```powershell
.\.venv\Scripts\python.exe gui.py
```

Choose a local MP4 and click **Preview Captions** to transcribe once and preview real words. Select text/outline colors, an installed font, font size, caption mode and timing settings; edits update the preview immediately. Click **Generate Captions** when ready to export. The default is white, outlined, bold single-word captions. The GUI lists installed font families, preferring Montserrat, Arial, or an installed sans-serif alternative. All choices use bold rendering. Its optional model folder picker overrides the default local model directory; it never downloads anything.

The scrollable output box streams the same progress/error messages as the CLI. Processing runs in a separate local Python process, leaving the window responsive. Settings are captured when generation starts; changing a control affects the next run. The button is disabled during a run, and the window asks you to wait if you try to close it mid-generation. On success it shows the output MP4 path and enables **Open containing folder**. Existing files are never overwritten, including SRT and ASS files.

In GUI multiword mode, the text picker sets the karaoke highlight color; upcoming words remain white. Pick a different text color to make the highlight visible. The GUI stays white by default as requested.

The first audio track is transcribed. All audio tracks are copied into the output without audio re-encoding, and the first video stream is encoded. Other video streams, embedded subtitles, chapters/attachments with format-dependent behavior, and advanced container features are outside this tool's preservation guarantees. Missing audio is reported as an FFmpeg error. Silence produces an empty SRT and an uncaptioned re-encode. Existing output files are never overwritten; rename/move them before retrying. If encoding fails after transcription, the SRT remains available.

Temporary WAV and encoded MP4 files are removed on success, normal errors, or Ctrl+C. A forced process termination may leave a `caption-*` temporary folder beside the source. Free space must accommodate the WAV (about 32 KB per audio second), temporary MP4, and final MP4 during copying.

## Quality

Video defaults to `libx264 -preset slow -crf 18`, keeping the input dimensions and without requesting a new frame rate. Lower CRF means larger files and less compression; `--crf 16` is available. Audio is stream-copied. Caption burning changes pixels and requires video re-encoding: CRF 18 is high quality, **not a guarantee of invisible loss**, and matching the original bitrate does not guarantee it either. This tool is intended for ordinary SDR MP4s; it does not implement HDR tone mapping or guarantee preservation of HDR/Dolby Vision metadata. Test a representative source before using it for archival/HDR material.

## Verification and troubleshooting

- `python caption.py --help` lists options without loading a model.
- A missing local model fails immediately instead of downloading it. Keep `model.bin`, `config.json`, and `tokenizer.json` in the model folder, along with the other downloaded files.
- Missing DLL errors on Windows generally call for the x64 Visual C++ runtime above.
- If `gui.py` reports missing `init.tcl` or Tk, repair/reinstall Python with Tcl/Tk enabled on Windows, or install `python3-tk` for the matching Linux Python. The CLI does not require Tk.
- Missing `ass`, `libx264`, or FFprobe means the installed FFmpeg distribution lacks required features; use a full build.
- CPU transcription may take longer than the video. Progress is printed as cues are transcribed, then the video encoding phase runs quietly.
- Python's offline settings/socket guard are defense in depth, not an OS sandbox for arbitrary native libraries. Disconnecting the network or applying a firewall rule gives an independent confirmation of offline operation.

Development validation: 40 automated tests cover timestamps, single-word overlap removal, ASS styling/colors/placement, rotated display dimensions, subtitle escaping, segment fallback, output protection, CLI orchestration, GUI command/progress/error forwarding, letterbox coordinate mapping, drag/resize calculations, custom ASS positions, playback clock scheduling, seeking, timer/capture cleanup, continuous-display timing across segments, last-word handling, rounded overlap/drop behavior, CLI/GUI style conflicts, minimum-duration clipping, real preview timing/karaoke, stale-cache invalidation, in-memory transport, and export reusing cached words without extraction/transcription, with local test doubles. Both scripts pass syntax checks. A real model transcription and FFmpeg encode were **not run in the authoring environment**, which lacked those dependencies/model files. Live playback and GUI window construction could not be verified because the authoring runtime lacks OpenCV and its Tcl initialization files; GUI and playback logic were tested without a window using test doubles.

References: [faster-whisper documentation](https://github.com/SYSTRAN/faster-whisper), [dependency declarations](https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/requirements.txt), [FFmpeg subtitle filters](https://www.ffmpeg.org/ffmpeg-filters.html#subtitles).


## Live video and caption preview

For an existing installation, install the new GUI dependency using the same Python environment:

```text
python -m pip install opencv-python
python gui.py
```

On Windows without activation:

```powershell
.\.venv\Scripts\python.exe -m pip install opencv-python
.\.venv\Scripts\python.exe gui.py
```

For an offline machine, include `opencv-python` when preparing `requirements-lock.txt` and `wheelhouse/` on the connected staging machine; the installation commands above already include it. Transfer/install the wheels with `--no-index` as described earlier. The CLI does not import or require OpenCV. On Linux, if OpenCV reports `libGL.so.1` missing, install your distribution's `libgl1` package (or provision it through the same offline package procedure).

- Selecting an MP4 loads its first frame into the preview panel. Pasting a path into the video field and pressing Enter also loads it. Frames fit the panel with their display aspect ratio preserved, with unused space around them. Resize the window or drag the divider to change panel width.
- **Play/Pause** advances frames using the video's OpenCV-reported FPS, including fractional rates. A monotonic clock and Tk `after()` callbacks prevent accumulated timer drift; if decoding/rendering falls behind, preview frames can be skipped to catch up. The last frame stops playback; Play then restarts from the beginning.
- Drag or click the seek slider to decode that frame immediately and pause there. The time label shows current/total time. Seeking can take a moment for high-resolution videos or long GOPs. Preview audio plays through local ffplay. FPS-based timing and duration are approximate for variable-frame-rate videos; this does not change the source video's encoding or transcription timestamps.
- Before transcription, a sample caption appears even while paused, with the selected bold font, text color, outline, and size. Edit **Sample text** to try a representative word or phrase; this text is never added to the transcript. After clicking **Preview Captions**, real timed words replace the sample. During genuine blank intervals there is no caption or draggable selection; seek to a visible word to adjust placement. Sample text edits are ignored while real captions are active. The blue selection border and corner handles are editor controls only, not an exported background box.
- Drag inside the caption border to move its center. Drag any corner handle toward/away from the center to shrink/grow the font, within the existing 16–240 range. The position percentages and font size update live, and the slider/input stay synchronized. Font, color, and size controls also redraw immediately while paused.
- Position is measured within the video, excluding letterbox space. Moving the center to the edges may clip long captions in the final video. The same position applies to all generated words/cues. **Reset placement and size** restores 50% width, 72% height, and font size 80. Settings persist when choosing another video in the same session; they are not saved between app launches.
- **Generate Captions** captures the current position and size and pauses playback. Percentages map to ASS coordinates as `x = PlayResX × percent_x / 100` and `y = 1920 × percent_y / 100`. Size is already in the existing 1920-high ASS units; no extra conversion is applied at generation. Untouched controls preserve the defaults.

The preview uses Tk's installed-font renderer, while final captions use FFmpeg/libass. Placement and size use the same coordinate scale, but font metrics, outlining, font substitution, and text wrapping can differ slightly. After transcription it uses the exact same cue-building and karaoke timing functions as export, including centisecond rounding, fill-gaps, and minimum duration. Real-frame timestamps from OpenCV select the active cue (falling back to frame index/FPS when the decoder has no timestamp). Tk typography is an approximation of the final libass render, not a pixel-identical render. OpenCV honors supported rotation metadata and sample aspect ratios through its FFmpeg backend. Only existing local MP4 paths are opened, with local-only FFmpeg protocols; no video is uploaded or downloaded. Unsupported codecs or missing OpenCV produce an error in the output box while leaving caption generation available.

OpenCV implementation references: [video capture](https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html) and [frame rate, seeking, aspect ratio, and orientation properties](https://docs.opencv.org/4.x/d4/d15/group__videoio__flags__base.html).

## Windows standalone installer build

The repository now includes `build.bat`, `outputs/packaging/OfflineVideoCaptions.iss`, `NOTICE/LICENSE.txt`, an application icon, external FFmpeg/FFprobe binaries, and the complete `models/faster-whisper-small` folder. The intended build host is Windows x64. The result is a PyInstaller **onedir** application plus an Inno Setup installer; FFmpeg and the model remain ordinary external files beside the executable so they are easy to audit and replace.

Install Inno Setup once before using the batch file: [Inno Setup downloads](https://jrsoftware.org/isdl.php). `build.bat` looks for `ISCC.exe` in the usual Inno Setup 6/7 Program Files locations, or honors an `ISCC` environment variable containing its full path. Rebuilding after any source change is simply running `build.bat` again. It cleans and recreates `build/` and `dist/`, then writes `release/OfflineVideoCaptions-Setup.exe`.

The build environment used to validate this project is an isolated Python 3.11 at `work/build-python`. A fresh build environment can be prepared with:

```powershell
py -3.11 -m venv work\build-python
work\build-python\Scripts\python.exe -m pip install "pyinstaller>=6.10,<7" "faster-whisper>=1.2,<2" opencv-python pillow
```

The exact PyInstaller command run by `build.bat` is:

```text
work\build-python\Scripts\pyinstaller.exe --noconfirm --clean --onedir --windowed --name OfflineVideoCaptions --icon app.ico --add-data "app.ico;." --add-data "work\build-python\tcl\tcl8.6;_tcl_data" --add-data "work\build-python\tcl\tk8.6;_tk_data" --add-binary "work\build-python\DLLs\_tkinter.pyd;." --add-binary "work\build-python\DLLs\tcl86t.dll;." --add-binary "work\build-python\DLLs\tk86t.dll;." --collect-all faster_whisper --collect-all ctranslate2 --collect-all onnxruntime --collect-all cv2 --collect-all av --hidden-import tkinter --hidden-import caption --hidden-import gui --paths outputs outputs\gui.py
```

After PyInstaller succeeds, the batch file copies `outputs/vendor/ffmpeg/ffmpeg.exe` and `ffprobe.exe` to `dist/OfflineVideoCaptions/ffmpeg/`, copies `outputs/models/faster-whisper-small/` to `dist/OfflineVideoCaptions/models/faster-whisper-small/`, and copies the optional Visual C++ x64 redistributable installer beside them. FFmpeg is not compiled into the executable and model weights are not put into the PyInstaller archive. At runtime the app checks these bundled locations first, then PATH only as a fallback.

The full Inno Setup script is [OfflineVideoCaptions.iss](C:/Users/fortc/Documents/Codex/2026-09-21/build-a-local-fully-offline-video/outputs/packaging/OfflineVideoCaptions.iss). It installs to a user-selected Program Files location, creates a Start Menu shortcut, offers a checked-by-default desktop shortcut task, registers an Add/Remove Programs uninstaller, and embeds the entire onedir output plus the NOTICE file into the Setup.exe. The exact batch file is [build.bat](C:/Users/fortc/Documents/Codex/2026-09-21/build-a-local-fully-offline-video/build.bat).

Build validation is deliberately fail-closed. Before PyInstaller runs, the batch file checks Python, PyInstaller, Inno Setup, source files, the model's required files, FFmpeg/FFprobe and the icon. It checks native imports before freezing, verifies the expected EXE/model/tools after copying, and stops if ISCC does not create the final Setup.exe. It does not silently create a partial installer.

The final installer has not been claimed as built in this environment: `ISCC.exe` is not installed here, and a clean-machine VM/sandbox is unavailable. The batch file is ready to run on a Windows build machine after Inno Setup is installed. A real frozen EXE launch and Setup.exe install should be run on that machine; they are not represented as completed merely because the source and packaging files exist. The current environment did validate native imports and the bundled FFmpeg/model assets, but it cannot honestly validate a clean-PC GUI launch without that external test machine.


## Minimum word duration

`--min-duration MS` applies only to `singleword` mode. The CLI default is **0 (disabled)**, so existing timing is unchanged. To enable a minimum, use a whole number from **100 to 800 milliseconds**:

```text
python caption.py input.mp4 --min-duration 250
python caption.py input.mp4 --fill-gaps --min-duration 250
python caption.py input.mp4 --min-duration 0
```

The GUI has a **Minimum word duration (ms)** checkbox plus a slider/input from 100–800 ms. It starts unchecked, with **250 ms preselected** for when you enable it. This preserves the old default while providing the suggested initial value. Switching to multiword clears/disables the singleword timing controls; nonzero `--min-duration` combined with `--style multiword` or `--highlight` is an error.

For each word, minimum duration extends its end if needed, but the next word's actual start (on the existing ASS 10 ms grid) is a hard upper bound. It never moves word starts, creates overlaps, or resurrects a word dropped because no interval was available. Non-multiples of 10 ms round up to the next 10 ms for the minimum. Fast adjacent words can therefore remain shorter than the requested minimum.

With continuous display OFF, a word spoken from 1.00–1.08 s with the next word at 1.50 s becomes 1.00–1.25 s for a 250 ms minimum. If the next word starts at 1.18 s, it stops at 1.18 s instead. With continuous display ON, the existing fill-gaps end is the upper bound; the minimum cannot extend beyond it, so filled intervals remain unchanged. This also preserves the final word's normal end in continuous mode. With continuous display OFF, the final word can be extended to meet the minimum because it has no following word, but nothing is visible beyond the end of the video. The raw grouped SRT remains unchanged.

## Real caption preview and transcription cache

1. Choose a video and click **Preview Captions**. The app extracts audio and runs the same local Whisper transcription as export, once. Progress appears in the output box. This step does **not** encode a video or create SRT/ASS output files. Its temporary WAV is removed afterward.
2. Word-level timestamps, segment fallback information and detected language are cached **in memory** for the current video/model. Press Play or scrub: real words appear/disappear at the computed cue times; multiword mode shows the same cumulative karaoke highlight schedule, with upcoming words white. Silence stays blank unless the timing controls extend a cue into it. Preview audio plays through local ffplay.
3. Change font, colors, size, position, mode, continuous display, or minimum duration. The overlay updates immediately, including on a paused frame. Timing changes recompute cues from the cached words; **they do not run Whisper again**. Clicking Preview Captions again also reuses the cache.
4. Click **Generate Captions** to do the separate full FFmpeg burn-in export, producing the usual captioned MP4, SRT and ASS. A matching cache is passed to the export process through a local memory pipe, skipping both audio extraction and Whisper. Export still captures your current settings and runs the high-quality video encode. Generating without a cache transcribes normally and also supplies that transcript to the GUI cache for subsequent preview/use.

Loading a different video, changing the model folder, or editing the input path invalidates the cache. The file's resolved path, size, and modification timestamp are checked before cache reuse, so replacing/changing a video also invalidates it. If inputs change while a job is running, its old transcript is discarded. No on-disk transcript cache is created: closing the GUI loses the cache, and returning to a previously selected different video requires Preview Captions again. Existing export files are still protected from overwrite, even when reusing a cache.

This preview is lightweight **after the one-time transcription**: it decodes frames and draws timed text in Tk instead of rendering a new MP4 on every edit. Transcription itself is still the same CPU-heavy local step. The final FFmpeg/libass render remains authoritative for exact font metrics, wrapping, outline appearance and exported video. The shared cue and karaoke schedule avoids a separate preview-only timing algorithm. There are no new Python dependencies, no API keys and no network calls.

### Correct words and preview audio

After Preview Captions finishes, double-click the visible caption directly on the video. Playback pauses and an inline entry appears over the caption. Enter or clicking away saves; Escape cancels. Singleword mode edits one word; multiword mode edits the whole visible cue. Same-count corrections retain word timings; changed word counts are distributed evenly across the original phrase span, so karaoke timing is approximate for those replacement words. Corrections immediately update the overlay and the same cache sent through `--transcript-stdin` on export. Scrub back to review the correction. Loading another video/model or closing the app discards edits. There is no separate transcript table.

Play starts local ffplay audio at the current preview position. Pause, scrubbing, loading another video, and closing stop that audio process. Playback uses approximate synchronization with the frame timer. Source runs use `outputs/vendor/ffmpeg/ffplay.exe`; packaged runs use `ffmpeg/ffplay.exe` beside the application. The build copies the complete FFmpeg folder and checks ffplay exists both before and after copying, failing if it is missing.
