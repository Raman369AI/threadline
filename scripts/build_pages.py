"""Build the static GitHub Pages site, including its pinned browser Python runtime."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tomllib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PYODIDE_VERSION = '0.28.3'  # CPython 3.13; tested by tests/pages_browser.py.
RUNTIME_HASHES = {
    'pyodide.js': '24a458425dcb4ea9836eb5ce26701d18cb769374e2b79247602ba605bf093278',
    'pyodide.asm.js': 'b22e5831eade9ff10e6fe2c811c68688cd91f10154377b4f80debcf5bafa1e56',
    'pyodide.asm.wasm': '5effb6a1a6cc4a1a85bec4622701aa797c031e1de923cbbaf2ad47abdc4ab325',
    'python_stdlib.zip': '71fee17f88a6260ec8c9c7c063533ee59c021fdc88a1ce76247378d3c4a35f4c',
    'pyodide-lock.json': 'f6e6f42f451f42affbbcddb00e8c9a3278dcbf399f57aab9f3f568839a7ff4a6',
    'LICENSE.pyodide': '1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5',
    'LICENSE.python': '78b12c3a81360b357002334f0e70ea0e92eebf7a9b358805c03c48484945f3bb',
}
LICENSE_URLS = {
    'LICENSE.pyodide': f'https://raw.githubusercontent.com/pyodide/pyodide/{PYODIDE_VERSION}/LICENSE',
    'LICENSE.python': 'https://raw.githubusercontent.com/python/cpython/v3.13.2/LICENSE',
}


def build(output: Path, runtime_cache: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name in ('index.html', 'styles.css', 'app.mjs', 'github.mjs', 'worker.js', 'sitemap.xml', 'social-preview.png'):
        shutil.copyfile(ROOT / 'pages' / name, output / name)
    shutil.copyfile(ROOT / 'LICENSE', output / 'LICENSE')
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for source in sorted((ROOT / 'threadline').rglob('*')):
            if source.is_file() and source.suffix in ('.py', '.html', '.css', '.js'):
                info = zipfile.ZipInfo(source.relative_to(ROOT).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(info, source.read_bytes())
    contents = archive.getvalue()
    filename = f'threadline-{hashlib.sha256(contents).hexdigest()[:16]}.zip'
    (output / filename).write_bytes(contents)
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    (output / 'build.json').write_text(json.dumps({'bundle':filename, 'version':version, 'pyodide':PYODIDE_VERSION}) + '\n')
    (output / '.nojekyll').touch()
    cache = runtime_cache / PYODIDE_VERSION
    cache.mkdir(parents=True, exist_ok=True)
    runtime = output / 'pyodide'
    runtime.mkdir(exist_ok=True)
    for name, expected_hash in RUNTIME_HASHES.items():
        cached = cache / name
        if not cached.is_file():
            url = LICENSE_URLS.get(name, f'https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/{name}')
            print(f'Downloading Pyodide {PYODIDE_VERSION}: {name}', flush=True)
            with urllib.request.urlopen(url, timeout=120) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != expected_hash:
                raise ValueError(f'Integrity check failed for {name}; runtime was not packaged')
            temporary = cached.with_suffix(cached.suffix + '.tmp')
            temporary.write_bytes(data)
            temporary.replace(cached)
        if hashlib.sha256(cached.read_bytes()).hexdigest() != expected_hash:
            raise ValueError(f'Integrity check failed for {cached}; remove that cache file and rebuild')
        shutil.copyfile(cached, runtime / name)
    (output / 'THIRD_PARTY.txt').write_text(
        'Threadline: MIT license (see LICENSE).\n\n'
        f'Pyodide {PYODIDE_VERSION}: Mozilla Public License 2.0 (see pyodide/LICENSE.pyodide).\n'
        f'Unmodified source: https://github.com/pyodide/pyodide/tree/{PYODIDE_VERSION}\n\n'
        'CPython 3.13.2: Python Software Foundation License and notices (see pyodide/LICENSE.python).\n'
        'Unmodified source: https://github.com/python/cpython/tree/v3.13.2\n'
    )
    print(f'Built {output} (Threadline {version}, Pyodide {PYODIDE_VERSION})')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build' / 'pages')
    parser.add_argument('--runtime-cache', type=Path, default=ROOT / 'build' / 'pyodide-cache')
    args = parser.parse_args()
    build(args.output.resolve(), args.runtime_cache.resolve())
