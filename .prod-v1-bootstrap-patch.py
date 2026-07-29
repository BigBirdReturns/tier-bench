from __future__ import annotations

import hashlib
from pathlib import Path

root = Path.cwd().resolve()
replacements = {
    'estate_lab/production.py': [
        (
            'Run it without installation:\n\n'
            '```text\n'
            'python -m estate_lab doctor\n'
            'python -m estate_lab conform --allow-exec --output conformance\n'
            '```',
            'Run it without installation through the path-pinned bootstrap:\n\n'
            '```text\n'
            'python surface-interop.py doctor\n'
            'python surface-interop.py conform --allow-exec --output conformance\n'
            '```',
        ),
        (
            '    python_launcher = b"from estate_lab.production_cli import main\\n\\nraise SystemExit(main())\\n"\n'
            "    shell_launcher = b'#!/usr/bin/env sh\\nset -eu\\nexec \"${PYTHON:-python3}\" -m estate_lab.production_cli \"$@\"\\n'\n"
            "    powershell_launcher = b'param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)\\n$ErrorActionPreference = \"Stop\"\\n$python = if ($env:PYTHON) { $env:PYTHON } else { \"python\" }\\n& $python -m estate_lab.production_cli @Arguments\\nexit $LASTEXITCODE\\n'\n",
            '    python_launcher = (\n'
            "        b'\"\"\"Path-pinned no-install Surface Interop bootstrap.\"\"\"\\n'\n"
            "        b'from __future__ import annotations\\n\\n'\n"
            "        b'import sys\\n'\n"
            "        b'from pathlib import Path\\n\\n'\n"
            "        b'ROOT = Path(__file__).resolve().parent\\n'\n"
            "        b'sys.path.insert(0, str(ROOT))\\n'\n"
            "        b'from estate_lab.production_cli import main  # noqa: E402\\n\\n'\n"
            "        b'raise SystemExit(main())\\n'\n"
            '    )\n'
            '    shell_launcher = (\n'
            "        b'#!/usr/bin/env sh\\n'\n"
            "        b'set -eu\\n'\n"
            "        b'ROOT=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\\n'\n"
            "        b'exec \"${PYTHON:-python3}\" \"$ROOT/surface-interop.py\" \"$@\"\\n'\n"
            '    )\n'
            '    powershell_launcher = (\n'
            "        b'param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)\\n'\n"
            "        b'$ErrorActionPreference = \"Stop\"\\n'\n"
            "        b'$python = if ($env:PYTHON) { $env:PYTHON } else { \"python\" }\\n'\n"
            "        b'$launcher = Join-Path $PSScriptRoot \"surface-interop.py\"\\n'\n"
            "        b'& $python $launcher @Arguments\\n'\n"
            "        b'exit $LASTEXITCODE\\n'\n"
            '    )\n',
        ),
    ],
    'estate_lab/tests/test_production.py': [
        (
            '            receipt, stdout, _ = run_bounded_process(\n'
            '                [sys.executable, "-m", "estate_lab", "--version"],\n'
            '                cwd=extract,\n'
            '                timeout_seconds=10,\n'
            '                max_capture_bytes=4096,\n'
            '            )\n'
            '            self.assertEqual(receipt.exit_code, 0)\n'
            '            self.assertEqual(stdout.decode("utf-8").strip(), "1.0.0")',
            '            receipt, stdout, stderr = run_bounded_process(\n'
            '                [sys.executable, str(extract / "surface-interop.py"), "--version"],\n'
            '                cwd=extract,\n'
            '                timeout_seconds=10,\n'
            '                max_capture_bytes=4096,\n'
            '            )\n'
            '            self.assertIn("PYTHONSAFEPATH", receipt.environment_keys)\n'
            '            self.assertEqual(receipt.exit_code, 0, stderr.decode("utf-8", errors="replace"))\n'
            '            self.assertEqual(stdout.decode("utf-8").strip(), "1.0.0")',
        ),
    ],
    'estate_lab/OPERATIONS.md': [
        (
            'It can run without installation through `python -m estate_lab`. An optional local installation',
            'It can run without installation through the path-pinned `python surface-interop.py` bootstrap; `python -m estate_lab` is reserved for an installed distribution. An optional local installation',
        ),
    ],
}
expected = {
    'estate_lab/production.py': '307ef497a80d056e12d78440eb0dc7d00d76d33343796cd329a33b0bff775148',
    'estate_lab/tests/test_production.py': 'df1009f7b8bce9d902bab598f03ac5858f3172c58814e940b38b5e5e8b0acbb3',
    'estate_lab/OPERATIONS.md': '7eed78aab070d949a8c4a690d6b382793440250a6d30f079686499e0bc386c37',
}
for relative, edits in replacements.items():
    path = root / relative
    text = path.read_text(encoding='utf-8')
    for old, new in edits:
        if text.count(old) != 1:
            raise SystemExit(f'production patch basis moved: {relative}')
        text = text.replace(old, new, 1)
    path.write_text(text, encoding='utf-8', newline='\n')
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected[relative]:
        raise SystemExit(f'production patch digest mismatch: {relative}: {actual}')
