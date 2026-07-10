from solution import count_matches
assert count_matches("a*c", ["abc","ac","ab"]) == 2
assert count_matches("[a-c]?", ["ax","cx","dx","a"]) == 2
try:
    count_matches("x[ab", ["x"]); raise SystemExit("expected ValueError")
except ValueError: pass
print("OK")
