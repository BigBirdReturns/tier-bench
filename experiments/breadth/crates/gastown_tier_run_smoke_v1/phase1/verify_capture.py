import sys
import json

def verify_capture(path):
    """Verify the capture file"""
    try:
        with open(path, 'r') as f:
            capture = json.load(f)
    except Exception as e:
        print(f"FAIL: Could not load capture JSON: {e}")
        return False

    argv = capture.get("argv", [])

    required_flags = ["--task-text", "--repo-path", "--file-scope", "--acceptance-command"]
    all_pass = True

    for flag in required_flags:
        if flag in argv:
            # Check if there's a value after the flag
            idx = argv.index(flag)
            if idx + 1 < len(argv):
                value = argv[idx + 1]
                # Check that the value is not a flag (doesn't start with --)
                if not value.startswith('--'):
                    print(f"PASS: {flag} present with value: {value}")
                else:
                    print(f"FAIL: {flag} has no valid value (followed by another flag)")
                    all_pass = False
            else:
                print(f"FAIL: {flag} present but no value follows")
                all_pass = False
        else:
            print(f"FAIL: {flag} not found in argv")
            all_pass = False

    return all_pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("FAIL: Missing capture JSON path argument")
        sys.exit(1)

    if verify_capture(sys.argv[1]):
        sys.exit(0)
    else:
        sys.exit(1)
