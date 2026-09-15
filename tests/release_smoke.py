"""Install a built wheel in a clean environment and review inert source outside the checkout."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    if not wheel.is_file(): parser.error('wheel does not exist')
    with tempfile.TemporaryDirectory(prefix='threadline-release-') as directory:
        root = Path(directory)
        environment = root / 'environment'
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ('Scripts' if os.name == 'nt' else 'bin')
        python = scripts / ('python.exe' if os.name == 'nt' else 'python')
        cli = scripts / ('threadline.exe' if os.name == 'nt' else 'threadline')
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        env['PYTHONNOUSERSITE'] = '1'
        subprocess.run([str(python), '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)],
                       cwd=root, env=env, check=True, timeout=60)
        target = root / 'source'
        target.mkdir()
        (target / 'api.py').write_text('raise RuntimeError("target must never execute")\nfrom helper import clean\ndef handle(value):\n    return clean(value)\n')
        (target / 'helper.py').write_text('def clean(value):\n    return value.strip()\n')
        result = subprocess.run([str(cli), 'inspect', str(target), '--entrypoint', 'api:handle'],
                                cwd=root, env=env, check=True, text=True, capture_output=True, timeout=30)
        workflow = json.loads(result.stdout)
        assert len(workflow['stages']['items']) >= 3, workflow
        with (root / 'server.log').open('w+') as log:
            process = subprocess.Popen([str(cli), 'review', str(target), '--port', '0', '--no-open'],
                                       cwd=root, env=env, stdout=log, stderr=log, text=True)
            try:
                deadline = time.monotonic() + 20
                url = None
                while time.monotonic() < deadline:
                    log.seek(0)
                    for line in log.read().splitlines():
                        if line.startswith('Open http://'): url = line[5:]
                    if url: break
                    if process.poll() is not None: raise RuntimeError('Packaged server exited before startup')
                    time.sleep(.05)
                assert url, 'Packaged server did not start'
                for path, expected in [('', b'Threadline'), ('app.js', b'/api/summary'), ('workflow.js', b'loadCallWorkflow'), ('styles.css', b'body'), ('api/summary', b'snapshotId')]:
                    with urllib.request.urlopen(url + path, timeout=5) as response:
                        assert response.status == 200
                        assert expected in response.read(), path
            finally:
                process.terminate()
                process.wait(timeout=10)
        print('PASS: clean wheel install, CLI workflow, loopback server, and bundled assets')


if __name__ == '__main__':
    main()
