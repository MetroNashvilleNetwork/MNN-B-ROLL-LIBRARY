ffmpeg + ffprobe (optional) — enables thumbnails, hover previews, and durations
===============================================================================

The B-Roll Library works WITHOUT these — you can still browse, search, filter,
and open files. Adding them turns on the nice stuff:

  * ffmpeg.exe   -> grid thumbnails and the short hover/detail video previews
  * ffprobe.exe  -> each clip's duration, resolution, and codec in the index

How to enable (one time, per computer or bundled with the app):

1. Download an FFmpeg build for Windows that includes BOTH ffmpeg.exe and
   ffprobe.exe, e.g. the "release essentials" build from
   https://www.gyan.dev/ffmpeg/builds/  or
   https://github.com/BtbN/FFmpeg-Builds/releases

2. Unzip it and copy these two files:

       ffmpeg.exe
       ffprobe.exe

   into THIS folder:

       <project>\tools\ffmpeg.exe
       <project>\tools\ffprobe.exe

3. In the gallery click "Re-index" (or run:  python main.py --index --full).
   Thumbnails and previews are generated the first time each clip is viewed and
   cached under <project>\cache, so browsing stays fast afterward.

The app auto-detects tools\ffmpeg.exe and tools\ffprobe.exe — no PATH changes
needed. You can also point config.json's "ffmpeg_path"/"ffprobe_path" at copies
elsewhere, or set "extract_video_metadata": false to turn metadata off.
