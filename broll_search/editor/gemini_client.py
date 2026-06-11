"""Gemini adapter for the AI director (google-genai SDK).

Isolated here so director.py stays SDK-free. The SDK client is created lazily;
tests inject a fake via `client=`. `make_gemini_client` returns None when no SDK
or credentials are available, so the pipeline cleanly falls back to the
heuristic planner.

NOTE (verify on first live run): exact model id, that uploaded video reaches a
usable state, and that `response_json_schema` is honored — these depend on the
live API and can't be exercised without a key."""

from __future__ import annotations

import json
import os
import time
from typing import Optional, Sequence

from .director import DirectorClient, EDL_RESPONSE_SCHEMA

DEFAULT_MODEL = "gemini-2.0-flash-001"   # video-capable + cheap; bump to a gemini-3 model when desired


class GeminiDirectorClient(DirectorClient):
    def __init__(self, model: str = DEFAULT_MODEL, api_key: Optional[str] = None,
                 vertexai: bool = False, project: Optional[str] = None,
                 location: Optional[str] = None, client=None,
                 processing_timeout: float = 120.0):
        self.model = model
        self.processing_timeout = processing_timeout
        if client is not None:
            self._client = client
        else:
            from google import genai
            if vertexai:
                self._client = genai.Client(vertexai=True, project=project, location=location)
            else:
                # api_key=None lets the SDK read GEMINI_API_KEY / GOOGLE_API_KEY from env
                self._client = genai.Client(api_key=api_key)

    def _wait_active(self, f):
        waited = 0.0
        while str(getattr(f, "state", "")).upper().endswith("PROCESSING") and waited < self.processing_timeout:
            time.sleep(2)
            waited += 2
            f = self._client.files.get(name=f.name)
        return f

    def _cleanup(self, files):
        for f in files:
            try:
                self._client.files.delete(name=f.name)
            except Exception:
                pass

    def generate_edl(self, prompt: str, proxy_paths: Sequence[str]) -> dict:
        files = []
        for p in proxy_paths:
            f = self._client.files.upload(file=p, config={"mime_type": "video/mp4"})
            files.append(self._wait_active(f))
        contents = list(files) + [prompt]
        resp = self._client.models.generate_content(
            model=self.model, contents=contents,
            config={"response_mime_type": "application/json",
                    "response_json_schema": EDL_RESPONSE_SCHEMA})
        self._cleanup(files)
        return json.loads(resp.text)


def make_gemini_client(model: str = DEFAULT_MODEL, api_key: Optional[str] = None,
                       vertexai: bool = False, project: Optional[str] = None,
                       location: Optional[str] = None, client=None) -> Optional[GeminiDirectorClient]:
    """Return a GeminiDirectorClient if usable, else None (-> heuristic fallback)."""
    if client is None:
        try:
            from google import genai  # noqa: F401
        except ImportError:
            return None
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not vertexai and not key:
            return None
        api_key = key
    try:
        return GeminiDirectorClient(model=model, api_key=api_key, vertexai=vertexai,
                                    project=project, location=location, client=client)
    except Exception:
        return None
