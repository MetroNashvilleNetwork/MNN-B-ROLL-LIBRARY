from broll_search.editor.scout import ClipScout
from broll_search.editor.music import MusicInfo
from broll_search.editor.planner import plan_scored
from broll_search.editor.edl import validate_edl


def _music():
    return MusicInfo("m.wav", 16.0, 120.0, [i * 0.5 for i in range(33)])


def test_plan_scored_ranks_by_quality_and_uses_best_window():
    scouts = [
        ClipScout("FX6_low.mov", score=1.0, best_in=2.0, best_out=4.0, duration=10, fps=24),
        ClipScout("DJI_high.mp4", score=9.0, best_in=1.0, best_out=3.5, duration=10, fps=24),
        ClipScout("FX6_mid.mov", score=5.0, best_in=0.0, best_out=2.0, duration=10, fps=24),
    ]
    edl = plan_scored(scouts, _music(), theme="t", target_total=6.0,
                      default_profile="rec709", pattern=(4, 2, 3))
    assert validate_edl(edl) == []
    # ranked best-first; strongest clip is the hook
    assert [c.source for c in edl.clips] == ["DJI_high.mp4", "FX6_mid.mov", "FX6_low.mov"]
    assert edl.clips[0].role == "hook" and edl.clips[-1].role == "closer"
    # profiles inferred; best window honored (DJI_high best_in=1.0, seg_dur=2.0 -> out=3.0)
    assert edl.clips[0].color_profile == "dji_dlogm"
    assert edl.clips[0].in_point == 1.0 and edl.clips[0].out_point == 3.0


def test_plan_scored_skips_zero_score_clips():
    scouts = [
        ClipScout("a.mov", score=0.0, best_in=0.0, best_out=2.0, duration=10, fps=24),
        ClipScout("FX6_good.mov", score=4.0, best_in=0.0, best_out=2.0, duration=10, fps=24),
    ]
    edl = plan_scored(scouts, _music(), theme="t", target_total=6.0,
                      default_profile="rec709", pattern=(4,))
    assert [c.source for c in edl.clips] == ["FX6_good.mov"]
