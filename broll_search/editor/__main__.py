"""CLI: python -m broll_search.editor --clips dev_media/clips --music dev_media/music"""

from __future__ import annotations

import argparse
import sys

from .pipeline import run_pipeline


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="broll_search.editor",
                                description="MNN Auto-Editor (Phase 1, offline)")
    p.add_argument("--clips", default="dev_media/clips", help="Folder of source clips")
    p.add_argument("--music", default="dev_media/music", help="Folder with a music track")
    p.add_argument("--out", default="output/latest", help="Output folder")
    p.add_argument("--theme", default="MNN B-Roll", help="Theme label for the video")
    p.add_argument("--duration", type=float, default=28.0, help="Target length (s)")
    p.add_argument("--profile", default="rec709",
                   choices=["rec709", "sony_slog3", "dji_dlogm"],
                   help="Default color profile when not inferable from filename")
    p.add_argument("--lut-dir", default="luts")
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--ffprobe", default="ffprobe")
    args = p.parse_args(argv)

    try:
        res = run_pipeline(args.clips, args.music, args.out, args.theme,
                           target_total=args.duration, default_profile=args.profile,
                           lut_dir=args.lut_dir, ffmpeg_path=args.ffmpeg,
                           ffprobe_path=args.ffprobe)
    except (RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Done. {len(res.edl.clips)} clips -> {res.vertical} and {res.landscape}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
