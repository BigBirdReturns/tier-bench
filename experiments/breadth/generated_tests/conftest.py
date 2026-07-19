"""Shared fixture for the machine-generated characterization tests in this
directory: every test_*_gen.py writes fixtures to bare relative paths like
Path("tmp_main_key.json") instead of a tempdir (an artifact of how they were
generated), which litters the repo root/scripts wherever pytest happens to be
invoked from. Rather than hand-edit 14+ pinned/mutation-verified generated
files, chdir each test into a throwaway tmp_path so those bare relative paths
land somewhere disposable and pytest cleans up automatically.
"""
import os
import pytest


@pytest.fixture(autouse=True)
def _chdir_tmp_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
