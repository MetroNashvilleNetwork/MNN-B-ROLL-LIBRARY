import json
from broll_search.editor.gemini_client import GeminiDirectorClient, make_gemini_client


class _FakeFile:
    def __init__(self, name):
        self.name = name
        self.uri = "uri://" + name
        self.mime_type = "video/mp4"
        self.state = "ACTIVE"


class _FakeFiles:
    def __init__(self):
        self.uploaded, self.deleted = [], []

    def upload(self, file, config=None):
        self.uploaded.append(str(file))
        return _FakeFile(str(file))

    def get(self, name):
        return _FakeFile(name)

    def delete(self, name):
        self.deleted.append(name)


class _FakeResp:
    text = '{"timeline":[{"clip_index":0,"in":0,"out":2,"role":"hook"}]}'


class _FakeModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return _FakeResp()


class _FakeClient:
    def __init__(self):
        self.files = _FakeFiles()
        self.models = _FakeModels()


def test_generate_edl_uploads_proxies_and_parses_json():
    fc = _FakeClient()
    c = GeminiDirectorClient(model="gemini-x", client=fc)
    data = c.generate_edl("the prompt", ["p0.mp4", "p1.mp4"])
    assert fc.files.uploaded == ["p0.mp4", "p1.mp4"]          # each proxy uploaded
    assert data["timeline"][0]["clip_index"] == 0            # response.text parsed
    call = fc.models.calls[0]
    assert call["model"] == "gemini-x"
    assert call["config"]["response_mime_type"] == "application/json"
    assert "response_json_schema" in call["config"]
    assert fc.files.deleted == ["p0.mp4", "p1.mp4"]          # uploaded files cleaned up


def test_make_gemini_client_none_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert make_gemini_client() is None


def test_make_gemini_client_builds_with_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    # inject a fake client so no real network/auth happens
    fc = _FakeClient()
    c = make_gemini_client(model="gemini-x", client=fc)
    assert isinstance(c, GeminiDirectorClient)
