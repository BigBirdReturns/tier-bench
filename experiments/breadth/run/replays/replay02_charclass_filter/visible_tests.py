from solution import charclass_filter
assert charclass_filter("[abc]", "abcd") == "abc"
assert charclass_filter("[a-z]", "aZz9") == "az"
assert charclass_filter("[!a]", "ab") == "b"
try:
    charclass_filter("[abc", "a"); raise SystemExit("expected ValueError")
except ValueError: pass
print("OK")
