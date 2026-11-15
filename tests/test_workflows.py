"""The GitHub workflows can't be run locally, and a typo in one only shows when a build machine reaches it (a stray apostrophe in a
comment inside a quoted script once cost a failed Linux build). So every shell step in every workflow gets a syntax check here."""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

yaml = pytest.importorskip('yaml')
WORKFLOWS = sorted((Path(__file__).resolve().parent.parent / '.github' / 'workflows').glob('*.yml'))


def shell_steps():
    for path in WORKFLOWS:
        data = yaml.safe_load(path.read_text())
        for job_name, job in (data.get('jobs') or {}).items():
            for step in job.get('steps') or []:
                if 'run' in step and step.get('shell', 'bash') == 'bash':           # PowerShell steps are not checked here
                    yield pytest.param(path.name, step.get('name', step['run'][:40]), step['run'], id=f'{path.stem}:{job_name}:{step.get("name", "step")}')


# On Windows the bash on the PATH is Microsoft's WSL launcher (it says no Linux distribution is installed), not a shell that can check
# a script. The shell is the same on every system, and the Linux and macOS runs check it.
needs_bash = pytest.mark.skipif(sys.platform == 'win32' or shutil.which('bash') is None, reason='needs a real bash')


@needs_bash
@pytest.mark.parametrize('workflow, name, script', list(shell_steps()))
def test_every_shell_step_is_valid_shell(workflow, name, script):
    script = re.sub(r'\$\{\{.*?\}\}', 'X', script, flags=re.S)             # GitHub fills these in before the shell sees the script
    with tempfile.NamedTemporaryFile('w', suffix='.sh', delete=False) as f:
        f.write(script)
    result = subprocess.run(['bash', '-n', f.name], capture_output=True, text=True)
    Path(f.name).unlink()
    assert result.returncode == 0, f'{workflow}: "{name}": {result.stderr}'


def test_the_workflows_parse_and_every_called_workflow_exists():
    assert len(WORKFLOWS) >= 5
    for path in WORKFLOWS:
        data = yaml.safe_load(path.read_text())
        for job in (data.get('jobs') or {}).values():
            called = job.get('uses')
            if called:
                assert (path.parent.parent.parent / called.removeprefix('./')).exists(), f'{path.name} calls {called}, which does not exist'


@needs_bash
def test_the_linux_check_script_is_valid_shell():
    script = Path(__file__).resolve().parent.parent / 'packaging' / 'linux-check.sh'
    result = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'linux-check.sh' in (WORKFLOWS[0].parent / 'build-apps.yml').read_text()       # and the workflow actually runs it
