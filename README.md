# Offline Video Captions

A fully offline Windows application for automatically generating, previewing, editing, and burning captions into videos.

The application uses **faster-whisper** for local speech-to-text transcription and **FFmpeg** for video processing. Videos and audio remain on the user's computer — no API key, account, paid service, or cloud transcription is required.

## Download

### Windows 10/11 x64

Download **`OfflineVideoCaptions-Setup.exe`** from the latest GitHub Release.

The installer contains the application, local transcription model, and required FFmpeg tools.

**No Python installation, API key, or command-line setup is required for normal use.**

## Features

* Fully offline video transcription
* No API keys, accounts, or cloud services
* Single-word CapCut/TikTok-style captions
* Multi-word karaoke-style captions
* Live video and caption preview
* Video playback with audio
* Scrubbing and seeking through the preview
* Drag captions directly on the video to reposition them
* Resize captions from the preview
* Customize font, size, text color, and outline color
* Double-click captions to correct transcription mistakes
* Continuous display option to keep words visible during pauses
* Adjustable minimum word duration
* Reuses cached transcription when adjusting captions
* Exports captioned MP4, SRT, and ASS files
* Standalone Windows installer

## How to Use

1. Install the application using `OfflineVideoCaptions-Setup.exe`.
2. Launch **Offline Video Captions**.
3. Select a local MP4 video.
4. Click **Preview Captions** to transcribe the video.
5. Preview and customize the captions.
6. Drag or resize captions directly in the video preview if needed.
7. Double-click a caption to correct a transcription mistake.
8. Click **Generate Captions** to export the finished video.

The application outputs a captioned MP4 along with separate SRT and ASS caption files.

> **Important:** The application will not overwrite existing output files. If a previously generated captioned video or its caption files already exist with the same output name, you will need to rename, move, or delete the existing files before generating again. The application will notify you if this happens.

## Caption Styles

### Single Word

Displays one word at a time for a short-form video style similar to captions commonly seen on TikTok, Shorts, and Reels.

Optional timing controls allow short words to remain visible longer and captions to stay displayed through pauses.

### Multiword

Displays groups of words with karaoke-style highlighting as the video plays.

## How It Works

The application uses **faster-whisper** with a local Whisper model to transcribe the video's audio and generate word-level timing information.

The preview system uses **OpenCV** and **Tkinter** to display the video and captions while allowing changes to positioning, size, styling, and transcription.

Transcription results are cached in memory so changing caption appearance or timing does not require Whisper to transcribe the video again.

When the final video is generated, **FFmpeg** burns the captions into the video while separate SRT and ASS caption files are also created.

## Technologies

* Python
* faster-whisper
* FFmpeg / FFprobe / FFplay
* Tkinter
* OpenCV
* PyInstaller
* Inno Setup
* Git / GitHub

## Development

I took this project from the initial idea to a working, packaged Windows application. My contributions included:

* Designing the application's features and user experience
* Planning and refining features throughout development
* Testing features and identifying bugs
* Debugging Python, Tkinter, PyInstaller, and packaging issues
* Diagnosing and resolving a Tcl/Tk build environment problem
* Testing fixes and troubleshooting errors
* Building and testing the standalone Windows installer
* Iteratively improving the application based on real testing

## Skills Demonstrated

* Debugging and troubleshooting
* Problem decomposition
* Prompt engineering
* AI-assisted software development
* Software testing and validation
* Iterative development
* Dependency and build environment management
* Application packaging and deployment
* Reading and interpreting error logs
* Git and GitHub version control

## AI Assistance

OpenAI Codex was used extensively as an AI coding assistant to generate and modify code throughout development.

I directed the development process through feature planning, prompt engineering, iterative prompting, testing, debugging, and validation. Much of the implementation was AI-generated, while I was responsible for guiding the project, identifying and troubleshooting problems, testing solutions, refining the application, and taking it from an idea to a working packaged Windows release.

This project represents my experience using AI as a software development tool while applying debugging, testing, problem-solving, and project-development skills.

## Running From Source

The standalone Windows installer is recommended for normal users.

Developers who want to run the project from source will need Python 3.11 and the project's required dependencies, including faster-whisper and OpenCV. FFmpeg, FFprobe, and the local Whisper model must also be available.

Main source files:

* `gui.py` — graphical application
* `caption.py` — transcription and caption generation

The packaged Windows version already includes the required runtime components and does not require this manual setup.

## Privacy / Offline Operation

Video transcription and processing are performed locally.

The application does not require an API key or cloud transcription service, and videos do not need to be uploaded to an external service for caption generation.

## Output

For an input video such as:

`video.mp4`

The application can generate:

* `video_captioned.mp4` — finished video with captions
* `video.srt` — standard subtitle file
* `video.ass` — styled subtitle file used for rendering

Existing output files are **never automatically overwritten**. Rename, move, or delete existing output files before generating another version with the same name.

## Platform

The standalone installer is intended for:

**Windows 10/11 x64**

The Python source can also be run manually in compatible environments with the required dependencies installed.

## License

This project is licensed under the **MIT License**. See `LICENSE` for details.
