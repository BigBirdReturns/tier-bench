"""
Held-out subject for proving a candidate lens (resource_lifetime).

Written to expose ONE class of defect that *looks correct*: a resource that
escapes its own `with` block and is used after it has been closed. The code reads
as clean (it uses a context manager!), so a general review tends to pass it. The
lens under test targets use-after-release across all paths, so it should surface
what the plain pass misses.

This file is the evidence a contributed lens is 'proven_on'. It is NOT tuned to
any lens's wording.
"""
import csv


def rows_of(path):
    """Return the parsed rows of a CSV file."""
    with open(path, newline="") as f:
        return csv.reader(f)            # reader is bound to f, which is closed on return


def first_row(path):
    return next(rows_of(path))          # iterating touches the closed file


def count_rows(path):
    return sum(1 for _ in rows_of(path))
