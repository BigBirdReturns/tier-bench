from lib import normalize_name

def main():
    if normalize_name("  Alice  ") != "alice":
        raise SystemExit("FAIL")
    print("OK")

if __name__ == "__main__":
    main()
