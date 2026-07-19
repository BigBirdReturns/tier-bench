import sys
import os
import json
import re

def redact_env():
    """Redact sensitive environment variables"""
    env = dict(os.environ)
    # Pattern to match env var names containing KEY, TOKEN, or SECRET (case-insensitive)
    sensitive_pattern = re.compile(r'(KEY|TOKEN|SECRET)', re.IGNORECASE)

    for key in env:
        if sensitive_pattern.search(key):
            env[key] = "***REDACTED***"

    return env

def main():
    capture = {
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "env": redact_env()
    }

    out_path = os.environ.get("TIER_CAPTURE_OUT")
    if not out_path:
        print("ERROR: TIER_CAPTURE_OUT env var not set")
        sys.exit(1)

    with open(out_path, 'w') as f:
        json.dump(capture, f, indent=2)

    print("CAPTURED-OK")
    sys.exit(0)

if __name__ == "__main__":
    main()
