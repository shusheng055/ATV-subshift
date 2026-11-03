"""Exact-build native caption profiles and reviewed CoreMedia relocations."""
from pathlib import Path
import json
import re


# These are stable source identifiers from the original reviewed bridge. Each
# newer profile must relocate every function, call site and range boundary.
COREMEDIA_RVAS = frozenset({
    0x289a40, 0x289db0, 0x8bdc20, 0x8bddc0, 0x8be730, 0x943f50,
    0x9474f0, 0x947960, 0x9486d6, 0x953e20, 0x954149, 0x95414f,
    0x954171, 0x954177, 0x95417c, 0x954182, 0x954210, 0x954410,
    0x954416, 0x955030, 0x9578b0, 0x9592b0, 0x959600, 0x95a350,
    0xb14f10, 0xb1d450, 0xb1d580,
})
LEGACY_VERSION = '1.1540.23558.0'


def load_profiles(native: Path):
    paths = [native / 'compatibility.json', *sorted(native.glob('compatibility-*.json'))]
    profiles = [json.loads(path.read_text('utf-8')) for path in paths]
    versions = [(p['package_name'], p['package_version']) for p in profiles]
    if len(set(versions)) != len(versions):
        raise RuntimeError('重复的 Apple TV 兼容配置。')
    for profile in profiles:
        relocation_map(profile)
    return profiles


def select_profile(package: Path, profiles):
    for profile in profiles:
        prefix = profile['package_name'] + '_' + profile['package_version'] + '_x64__'
        if package.name.startswith(prefix):
            return profile
    raise RuntimeError('此 Apple TV 版本尚未适配，请更新 ATV subshift。')


def relocation_map(profile):
    raw = profile.get('coremedia_rvas')
    if raw is None:
        if profile['package_version'] != LEGACY_VERSION:
            raise RuntimeError('新版 Apple TV 缺少字幕接口适配。')
        return {}
    result = {int(k, 16): v for k, v in raw.items()}
    if set(result) != COREMEDIA_RVAS or any(type(v) is not int or not 0 < v < 0x10000000 for v in result.values()):
        raise RuntimeError('Apple TV 字幕接口适配不完整。')
    if len(set(result.values())) != len(result):
        raise RuntimeError('Apple TV 字幕接口地址重复。')
    return result


def relocate_bridge(source: str, profile):
    mapping = relocation_map(profile)
    if not mapping:
        return source
    # One pass also covers the two CTLine caller strings and the timing arrays.
    # Object-field offsets and other module addresses remain byte-for-byte intact.
    return re.sub(r'\b0x[0-9a-fA-F]+\b',
                  lambda m: hex(mapping[int(m[0], 16)]) if int(m[0], 16) in mapping else m[0],
                  source)
