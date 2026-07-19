import subprocess
import os
import tempfile
import sys

def run_selftest():
    """Run the selftest"""
    # Create a temporary file for capture output
    fd, capture_out = tempfile.mkstemp(suffix='.json')
    os.close(fd)

    try:
        # Run capture_fixture.py with sample values
        script_dir = os.path.dirname(os.path.abspath(__file__))
        capture_script = os.path.join(script_dir, "capture_fixture.py")

        env = os.environ.copy()
        env["TIER_CAPTURE_OUT"] = capture_out

        # Run capture_fixture.py
        result = subprocess.run(
            [sys.executable, capture_script,
             "--task-text", "sample_task",
             "--repo-path", "/path/to/repo",
             "--file-scope", "src/",
             "--acceptance-command", "pytest"],
            env=env,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"FAIL: capture_fixture.py failed with return code {result.returncode}")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            return False

        if "CAPTURED-OK" not in result.stdout:
            print(f"FAIL: capture_fixture.py did not print CAPTURED-OK")
            print(f"stdout: {result.stdout}")
            return False

        # Run verify_capture.py
        verify_script = os.path.join(script_dir, "verify_capture.py")
        result = subprocess.run(
            [sys.executable, verify_script, capture_out],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"FAIL: verify_capture.py failed with return code {result.returncode}")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            return False

        # Check output contains all PASS
        output_lines = result.stdout.strip().split('\n')
        for line in output_lines:
            if "FAIL" in line:
                print(f"FAIL: verify_capture.py found failures: {line}")
                return False

        print("PHASE1-SELFTEST OK")
        return True

    finally:
        # Clean up
        if os.path.exists(capture_out):
            os.remove(capture_out)

if __name__ == "__main__":
    if run_selftest():
        sys.exit(0)
    else:
        sys.exit(1)
