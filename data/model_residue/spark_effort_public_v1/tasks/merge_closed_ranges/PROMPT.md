Return only one complete Python source file, with no Markdown fences or commentary.

Implement:

    def merge_closed_ranges(ranges):

Each input item is a pair of integers describing a closed interval. Normalize reversed endpoints, sort the normalized intervals, and merge intervals that overlap or touch as integer sets. For example, `(1, 3)` and `(4, 7)` merge because there is no integer gap; `(1, 3)` and `(5, 7)` do not. Return a new list of `(start, end)` tuples sorted by start. Do not mutate the input.

