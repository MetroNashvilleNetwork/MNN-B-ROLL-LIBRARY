from broll_search.web.media import MediaEngine


def test_lock_dict_prunes_after_release(tmp_path, monkeypatch):
    monkeypatch.setattr("broll_search.web.media._resolve_tool", lambda *a: None)
    eng = MediaEngine(cache_dir=tmp_path)
    eng._locks_max = 4
    keys = [f"k{i}" for i in range(8)]
    for k in keys:
        lock = eng._lock_for(k)
        lock.acquire()
        lock.release()
        eng._maybe_prune_lock(k, lock)
    assert len(eng._locks) <= eng._locks_max
