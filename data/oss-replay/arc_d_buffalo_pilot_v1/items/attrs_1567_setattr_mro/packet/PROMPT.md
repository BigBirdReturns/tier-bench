You are a cold OSS diagnostic subject. This packet is complete.
Do not browse, call tools, inspect a repository, or assume unseen files. Analyze only
the public problem report and pinned source excerpt below. Do not claim that you ran
tests. This is an exploratory observation, not a benchmark or an upstream verdict.

Return exactly these five Markdown sections:

1. `## Diagnosis` — the concrete execution path and root cause, including uncertainty.
2. `## Minimal change design` — the smallest coherent change surface and its invariants.
3. `## Regression matrix` — tests, inputs, and expected results, including boundaries.
4. `## Candidate residue` — one falsifiable reusable rule plus its applicability limit.
5. `## Confidence and disconfirmation` — confidence from 0 to 1 and evidence that would
   disprove or materially change the answer.

## Public problem report

An attrs-generated descendant can reset the wrong inherited `__setattr__` across
an intermediate non-attrs class. The observed failure is most visible for a
slotted chain where a mutable descendant remains subject to an ancestor's frozen
setter and raises `FrozenAttributeError` on assignment.

The library must distinguish attrs-owned setter machinery from a user-owned
intermediate `__setattr__`, for both slotted and dict-backed classes. Diagnose the
resolution rule and propose boundary tests. The pinned source is unusually
high-hint: it already documents one known confused case, so treat this as a
calibration observation rather than a clean blindness claim.

## Pinned source excerpt

```python
# python-attrs/attrs @ d2fbfccc1ce77dcc927a86eae9521c95dc4e289c
# Curated allowlisted excerpts derived from src/attr/_make.py.
# Unrelated lines and some prose are elided; this packet is not a byte slice.
# The complete delivered PROMPT hash, not this upstream blob hash, is the subject authority.
# 793bfd89d6cd51f194dbc7ca9062f502ac172f09

def _patch_original_class(self):
    """Apply accumulated methods and return the class."""
    cls = self._cls
    base_names = self._base_names

    if self._delete_attribs:
        for name in self._attr_names:
            if (
                name not in base_names
                and getattr(cls, name, _SENTINEL) is not _SENTINEL
            ):
                with contextlib.suppress(AttributeError):
                    delattr(cls, name)

    for name, value in self._cls_dict.items():
        setattr(cls, name, value)

    # If we've inherited an attrs __setattr__ and don't write our own,
    # reset it to object's.
    if not self._wrote_own_setattr and getattr(
        cls, "__attrs_own_setattr__", False
    ):
        cls.__attrs_own_setattr__ = False

        if not self._has_custom_setattr:
            cls.__setattr__ = _OBJ_SETATTR

    return cls


def _create_slots_class(self):
    """Build and return a new class with a `__slots__` attribute."""
    cd = {
        k: v
        for k, v in self._cls_dict.items()
        if k not in (*tuple(self._attr_names), "__dict__", "__weakref__")
    }

    # If our class doesn't have its own implementation of __setattr__
    # (either from the user or by us), check the bases, if one of them has
    # an attrs-made __setattr__, that needs to be reset. We don't walk the
    # MRO because we only care about our immediate base classes.
    # XXX: This can be confused by subclassing a slotted attrs class with
    # XXX: a non-attrs class and subclass the resulting class with an attrs
    # XXX: class.  See `test_slotted_confused` for details.  For now that's
    # XXX: OK with us.
    if not self._wrote_own_setattr:
        cd["__attrs_own_setattr__"] = False

        if not self._has_custom_setattr:
            for base_cls in self._cls.__bases__:
                if base_cls.__dict__.get("__attrs_own_setattr__", False):
                    cd["__setattr__"] = _OBJ_SETATTR
                    break

    # Traverse the MRO to collect existing slots
    # and check for an existing __weakref__.
    existing_slots = {}
    weakref_inherited = False
    for base_cls in self._cls.__mro__[1:-1]:
        if base_cls.__dict__.get("__weakref__", None) is not None:
            weakref_inherited = True
        existing_slots.update(
            {
                name: getattr(base_cls, name)
                for name in getattr(base_cls, "__slots__", [])
            }
        )


# Curated existing behavior derived from tests/test_setattr.py.
# f44abf65847a433b83ad13e197d2a59ccc66c38a
import pytest
import attr
from attr import setters


@attr.s
class WithOnSetAttrHook:
    x = attr.ib(on_setattr=lambda *args: None)


def test_setattr_reset_if_no_custom_setattr(slots):
    def boom(*args):
        pytest.fail("Must not be called.")

    @attr.s
    class Hooked:
        x = attr.ib(on_setattr=boom)

    @attr.s(slots=slots)
    class NoHook(WithOnSetAttrHook):
        x = attr.ib()

    assert NoHook.__setattr__ == object.__setattr__
    assert 1 == NoHook(1).x
    assert Hooked.__attrs_own_setattr__
    assert not NoHook.__attrs_own_setattr__
    assert WithOnSetAttrHook.__attrs_own_setattr__


def test_setattr_inherited_do_not_reset(slots):
    class A:
        def __setattr__(self, *args):
            pass

    @attr.s(slots=slots)
    class B(A):
        pass

    assert B.__setattr__ == A.__setattr__

    @attr.s(slots=slots)
    class C(B):
        pass

    assert C.__setattr__ == A.__setattr__


def test_slotted_class_can_have_custom_setattr():
    @attr.s(slots=True)
    class A:
        def __setattr__(self, key, value):
            raise SystemError

    with pytest.raises(SystemError):
        A().x = 1


@pytest.mark.xfail(raises=attr.exceptions.FrozenAttributeError)
def test_slotted_confused():
    """
    If we have a in-between non-attrs class, setattr reset detection
    should still work, but currently doesn't.

    It works with dict classes because we can look the finished class and
    patch it. With slotted classes we have to deduce it ourselves.
    """

    @attr.s(slots=True)
    class A:
        x = attr.ib(on_setattr=setters.frozen)

    class B(A):
        pass

    @attr.s(slots=True)
    class C(B):
        x = attr.ib()

    C(1).x = 2
```
