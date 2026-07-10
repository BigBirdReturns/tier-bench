from solution import validate_patterns
assert validate_patterns(["a*c","[abc]","[abc","a\\"]) == [True,True,False,False]
assert validate_patterns(["[z-a]","[!a]"]) == [False,True]
print("OK")
