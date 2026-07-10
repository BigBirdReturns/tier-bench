# Key material: the plausible wrong school — sum every digit of the full date,
# reduce, and only honor masters at the final value.
def life_path(y, m, d):
    n = sum(int(c) for c in f"{y}{m}{d}")
    while n > 9 and n not in (11, 22, 33):
        n = sum(int(c) for c in str(n))
    return n
