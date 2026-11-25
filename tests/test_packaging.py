"""Check the public ZIP and installer syntax without installing or downloading."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")


@pytest.mark.skipif(not POWERSHELL, reason="Windows packaging uses PowerShell")
def test_public_package_contains_source_not_local_state(tmp_path):
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(ROOT / "packaging" / "make_dist.ps1"), "-Out", str(tmp_path), "-Zip"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    from ckapp import __version__
    archive = tmp_path / f"CorridorKey2-Workbench-{__version__}.zip"
    digest, name = Path(str(archive) + ".sha256").read_text().strip().split("  ")
    assert name == archive.name
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest
    with zipfile.ZipFile(archive) as package:
        prefix = "CorridorKey2 Workbench/"
        files = {n: package.read(n) for n in package.namelist() if not n.endswith("/")}
        manifest = json.loads(files[prefix + "package-manifest.json"])
        assert manifest["version"] == __version__
        assert len(manifest["source_revision"]) == 40
        expected = {prefix + row["path"] for row in manifest["files"]}
        assert set(files) == expected | {prefix + "package-manifest.json"}
        for row in manifest["files"]:
            data = files[prefix + row["path"]]
            assert len(data) == row["size"]
            assert hashlib.sha256(data).hexdigest() == row["sha256"]
        assert prefix + "Setup.bat" in files
        assert prefix + "app/LICENSE" in files
        assert prefix + "app/ckapp/app/assets/fonts/OFL-Geist.txt" in files
        assert prefix + "app/licenses/Lucide.txt" in files
        for name in files:
            assert not {".git", ".venv", ".cache", "__pycache__", "models", "tests"} & set(Path(name).parts)
            assert not name.endswith((".safetensors", ".pt", ".npz", ".pyc", ".key", ".pem"))


@pytest.mark.skipif(not POWERSHELL, reason="Windows installer uses PowerShell")
def test_setup_and_packager_parse_without_running():
    # The parser reads scripts only: no setup side effects, GPU use or downloads.
    script = """
$ErrorActionPreference = 'Stop'
Get-ChildItem -LiteralPath packaging -Filter '*.ps1' | ForEach-Object {
    $tokens = $null; $errors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
}
"""
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
