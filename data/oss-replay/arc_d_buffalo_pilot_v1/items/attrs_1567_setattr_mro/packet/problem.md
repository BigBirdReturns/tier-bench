An attrs-generated descendant can reset the wrong inherited `__setattr__` across
an intermediate non-attrs class. The observed failure is most visible for a
slotted chain where a mutable descendant remains subject to an ancestor's frozen
setter and raises `FrozenAttributeError` on assignment.

The library must distinguish attrs-owned setter machinery from a user-owned
intermediate `__setattr__`, for both slotted and dict-backed classes. Diagnose the
resolution rule and propose boundary tests. The pinned source is unusually
high-hint: it already documents one known confused case, so treat this as a
calibration observation rather than a clean blindness claim.
