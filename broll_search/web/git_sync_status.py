"""This app's entry in the GitHub poller's sync status file.

C:\\Share\\apps\\autobroll-sync writes C:\\Share\\apps\\data\\git-sync\\status.json after
every poll. Admins see a "Git sync conflict" alert built from this app's entry
(static git-sync-alert.js). Shared verbatim by every app the poller syncs.
"""
import json
import os

DEFAULT_PATH = r'C:\Share\apps\data\git-sync\status.json'
FIELDS = ('state', 'message', 'branch', 'path', 'since', 'last_checked', 'failures',
          'local_changes', 'remote_commits')


def is_admin(user):
    """Only MNN Control's admin role, not the broader roles some apps treat as admin."""
    return isinstance(user, dict) and user.get('role') == 'admin'


def load(repo, path=None):
    path = path or os.environ.get('GIT_SYNC_STATUS_PATH') or DEFAULT_PATH
    try:
        with open(path, encoding='utf-8-sig') as handle:
            entry = (json.load(handle).get('repos') or {}).get(repo)
    except (OSError, ValueError, AttributeError):
        entry = None
    if not isinstance(entry, dict):
        return {'repo': repo, 'state': 'unknown'}
    result = {field: entry.get(field) for field in FIELDS}
    result['repo'] = repo
    for key in ('local_changes', 'remote_commits'):
        value = result.get(key) or []
        result[key] = [value] if isinstance(value, str) else [str(item) for item in value]
    return result
