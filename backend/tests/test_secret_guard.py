"""Exercise the actual checker against a Git index, never a real credential."""
import importlib.util
from pathlib import Path
import subprocess

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check-secrets.py'


def test_index_guard_rejects_secrets_even_if_worktree_was_cleaned(tmp_path):
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)
    git('init')
    # Assemble a synthetic token so no live-looking value lives in source history.
    fake = 'gh' + 'p_' + 'x' * 36
    file = tmp_path / 'settings.txt'
    file.write_text('token=' + fake)
    git('add', 'settings.txt')
    file.write_text('token=removed from working tree')
    result = subprocess.run([__import__('sys').executable, str(SCRIPT), '--staged'], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1
    assert 'GitHub token' in result.stdout
    assert fake not in result.stdout + result.stderr
    git('add', 'settings.txt')
    result = subprocess.run([__import__('sys').executable, str(SCRIPT), '--staged'], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0
    (tmp_path / '.env').write_text('TOKEN=short-but-private')
    git('add', '.env')
    result = subprocess.run([__import__('sys').executable, str(SCRIPT), '--staged'], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1 and 'credential filename' in result.stdout


def test_examples_are_allowed_but_private_backups_are_not():
    spec = importlib.util.spec_from_file_location('secret_guard', SCRIPT)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    assert not list(guard.findings('backend/.env.example', b'API_KEY="replace-with-your-own-key"'))
    assert list(guard.findings('backups/bootstrap-passwords.json', b'{}'))
