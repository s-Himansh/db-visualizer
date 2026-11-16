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
@pytest.mark.parametrize('script, run_by', [('linux-check.sh', 'build-apps.yml'), ('linux-desktop-check.sh', 'linux-desktop-check.yml')])
def test_the_linux_check_scripts_are_valid_shell_and_a_workflow_runs_them(script, run_by):
    path = Path(__file__).resolve().parent.parent / 'packaging' / script
    result = subprocess.run(['bash', '-n', str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert script in (WORKFLOWS[0].parent / run_by).read_text()                            # and the workflow actually runs it


def test_the_desktop_drive_script_compiles():
    import py_compile
    drive = Path(__file__).resolve().parent.parent / 'packaging' / 'linux_desktop_drive.py'
    py_compile.compile(str(drive), doraise=True)
    assert 'linux_desktop_drive.py' in (drive.parent / 'linux-desktop-check.sh').read_text()


def test_the_desktop_check_is_manual_only():
    """It downloads a 270 MB release and starts a desktop: run by hand, never on a push (the branch version ran on every push)."""
    data = yaml.safe_load((WORKFLOWS[0].parent / 'linux-desktop-check.yml').read_text())
    triggers = data.get('on') or data.get(True)                                            # YAML reads a bare "on" as True
    assert set(triggers) == {'workflow_dispatch'}
    assert triggers['workflow_dispatch']['inputs']['tag']['required'] is True
