"""Install the local toolchain. Run from any directory; Python >= 3.11.5 required."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd=ROOT):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True, env={**os.environ, 'PLAYWRIGHT_SKIP_BROWSER_GC': '1'})


def setup(browser=None):
    if sys.version_info < (3, 11, 5):
        raise RuntimeError('Python 3.11.5 or newer is required')
    node, npm = shutil.which('node'), shutil.which('npm')
    if not node or not npm:
        raise RuntimeError('Install Node.js 22+ (including npm), then rerun bootstrap')
    major = int(subprocess.check_output([node, '--version'], text=True).strip().lstrip('v').split('.')[0])
    if major < 22:
        raise RuntimeError('Node.js 22+ is required')
    if browser and not Path(browser).expanduser().is_file():
        raise RuntimeError('--browser must point to an existing browser executable')
    run([sys.executable, ROOT / 'workflow/download_sources.py'])
    env = ROOT / 'workflow/.venv'
    if not env.exists():
        venv.EnvBuilder(with_pip=True).create(env)
    python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    run([python, '-m', 'pip', 'install', '-r', 'workflow/requirements.lock.txt'])
    run([npm, 'ci'], ROOT / 'workflow')
    playwright = ROOT / 'workflow/node_modules/playwright/cli.js'
    if browser:
        executable = str(Path(browser).expanduser().resolve())
    else:
        run([node, playwright, 'install', 'chromium'])
        executable = subprocess.check_output(
            [node, '-e', "console.log(require('playwright').chromium.executablePath())"],
            cwd=ROOT / 'workflow', text=True).strip()
    # Do not publish this file: machine-specific configuration is generated here.
    runtime = {'node': node, 'node_packages': str(ROOT / 'workflow/node_modules'), 'browser': executable}
    config = ROOT / 'workflow/runtime.json'
    if config.exists():
        backup = ROOT / 'workflow/runtime.previous.json'
        if not backup.exists():
            shutil.copy2(config, backup)
    config.write_text(json.dumps(runtime, indent=2) + '\n', encoding='utf-8')
    run([python, 'workflow/wechat.py', 'doctor'])
    run([node, 'scripts/check_runtime.mjs'])
    print('Setup complete. Next read workflow/skills/wechat-article-workflow/SKILL.md')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', help='Use an existing Chrome/Chromium executable instead of downloading Chromium')
    args = parser.parse_args()
    try:
        setup(args.browser)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Setup failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
