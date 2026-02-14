def area_rect(w, h):
    return w*h

def area_square(s):
    return s*s

def main():
    if area_square(3) != 9:
        raise SystemExit("FAIL")
    if area_rect(2, 5) != 10:
        raise SystemExit("FAIL")
    print("OK")

if __name__ == "__main__":
    main()
