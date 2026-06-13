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
    p.add_argument("--no-scored", action="store_true",
                   help="Use filename order instead of quality scouting")
    p.add_argument("--director", action="store_true",
                   help="Use the Gemini AI director (needs GEMINI_API_KEY); falls back to scoring if unavailable")
    p.add_argument("--no-brand", action="store_true", help="Skip the MNN title/outro cards")
    p.add_argument("--look-strength", type=float, default=0.4,
                   help="House-look intensity 0..1 (low = cleaner/more natural)")
    # 8d — cinematic escape-hatch flags (all default to the cinematic-ON behaviour)
    p.add_argument("--no-stabilize", action="store_true",
                   help="Disable per-clip stabilization (overrides cinematic default of ON)")
    p.add_argument("--no-exposure", action="store_true",
                   help="Disable per-clip exposure correction (overrides cinematic default of ON)")
    p.add_argument("--slowmo-ceiling", type=float, default=0.85,
                   help="Max fraction of total runtime that may be slow-mo (default 0.85)")
    p.add_argument("--outro", choices=["card", "fade", "none"], default="fade",
                   help="Ending: 'fade' = fade to black (default), 'card' = branded outro card, 'none' = hard cut")
    p.add_argument("--slowmo-all", action="store_true",
                   help="Full slow-motion: every eligible clip plays slow (overrides the slow-mo ceiling)")
    p.add_argument("--slowmo-factor", type=float, default=0.0,
                   help="Playback slowdown. 0 = optical max (2.5x for 60fps, frame-exact); "
                        ">2.5 uses motion interpolation for smooth slower-than-optical slow-mo")
    p.add_argument("--preview", action="store_true",
                   help="Fast preview render (2160p prescale, for dev/Mac); omit for 4K-final quality")
    args = p.parse_args(argv)

    director_client = None
    if args.director:
        from .gemini_client import make_gemini_client
        director_client = make_gemini_client()
        if director_client is None:
            print("Note: --director set but no Gemini client (set GEMINI_API_KEY). "
                  "Falling back to quality scoring.", file=sys.stderr)

    try:
        res = run_pipeline(args.clips, args.music, args.out, args.theme,
                           target_total=args.duration, default_profile=args.profile,
                           lut_dir=args.lut_dir, ffmpeg_path=args.ffmpeg,
                           ffprobe_path=args.ffprobe,
                           scored=not args.no_scored,
                           director_client=director_client,
                           brand=not args.no_brand,
                           look_strength=args.look_strength,
                           stabilize=not args.no_stabilize,
                           exposure=not args.no_exposure,
                           slowmo_ceiling=args.slowmo_ceiling,
                           final_quality=not args.preview,
                           outro=args.outro,
                           slowmo_all=args.slowmo_all,
                           slowmo_factor=args.slowmo_factor)
    except (RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Done. {len(res.edl.clips)} clips -> {res.vertical} and {res.landscape}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
