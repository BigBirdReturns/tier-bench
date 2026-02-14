from client import fetch_json

def main():
    data = fetch_json("data:application/json,%7B%22x%22%3A%201%7D")
    if data.get("x") != 1:
        raise SystemExit("FAIL")
    print("OK")

if __name__ == "__main__":
    main()
