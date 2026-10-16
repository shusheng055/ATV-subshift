"""Endpoint-scoped DPAPI keys; preserve the existing single-key file verbatim."""
from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit

from .settings import DATA, _protect, load_key, save_key


def credential_scope(url: str):
    value = url.strip().rstrip('/')
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, '', ''))


class CredentialStore:
    def __init__(self, legacy_url: str, directory=DATA):
        self.directory = directory
        self.path = directory / 'provider-credentials.dpapi'
        self.legacy_scope = credential_scope(legacy_url)
        self.keys = {}
        self.loaded = False
        self.error = False
        if self.path.exists():
            try:
                raw = json.loads(_protect(self.path.read_bytes(), decrypt=True).decode('utf-8'))
                if not isinstance(raw['legacy_scope'], str) or not isinstance(raw['keys'], dict):
                    raise ValueError()
                if not all(isinstance(k, str) and isinstance(v, str) for k, v in raw['keys'].items()):
                    raise ValueError()
                self.legacy_scope, self.keys = raw['legacy_scope'], raw['keys']
                self.loaded = True
            except (OSError, ValueError, KeyError, TypeError, UnicodeError):
                # A broken vault must never rebind the old key to a different URL.
                self.error = True

    def get(self, url: str):
        if self.error:
            return ''
        scope = credential_scope(url)
        if scope in self.keys:
            return self.keys[scope]
        return load_key(self.directory) if scope == self.legacy_scope else ''

    def ensure_binding(self):
        if self.error:
            raise OSError('无法读取服务商 Key 文件；原文件已保留。')
        if not self.loaded:
            self._write()

    def set(self, url: str, key: str):
        self.ensure_binding()
        scope = credential_scope(url)
        if self.get(url) == key:
            return
        if scope == self.legacy_scope:
            save_key(key, self.directory)
        else:
            old = self.keys.copy()
            self.keys[scope] = key
            try:
                self._write()
            except OSError:
                self.keys = old
                raise

    def _write(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        raw = json.dumps({'legacy_scope': self.legacy_scope, 'keys': self.keys}, ensure_ascii=False)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(_protect(raw.encode('utf-8')))
        temporary.replace(self.path)
        self.loaded = True
