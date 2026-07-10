# Key material: correct implementation — masters terminal at every stage.
def _reduce(n):
    while n > 9 and n not in (11, 22, 33):
        n = sum(int(c) for c in str(n))
    return n


def life_path(y, m, d):
    return _reduce(_reduce(m) + _reduce(d) + _reduce(sum(int(c) for c in str(y))))
