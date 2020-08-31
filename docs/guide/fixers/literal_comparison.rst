Literal Comparison
==================

.. seealso:: pylint `literal-comparison (R0123)
   <https://pylint.readthedocs.io/en/latest/technical_reference/features.html>`_

**tl;dr:** it's possible for ``x is 1`` to be ``False``, but ``x == 1`` to be
``True``, and when/whether this happens depends entirely on implementation
details of Python. It is always a mistake to compare using ``is`` against a
literal.

What the meaning of ``is`` is
-----------------------------

For most types, most of the time, ``x == y`` means something like
"``x`` and ``y`` are interchangeable, as long as you aren't mutating them".

``x is y``, in contrast, has a strict and narrow meaning. It means "``x``
*refers to the same object* as ``y``". As a consequence, it means ``x`` and
``y`` are interchangeable in *all* circumstances, even if you are mutating them!

Mutable Literals
~~~~~~~~~~~~~~~~

Because mutable literals are defined to always evaluate to a new object,
expressions like ``x is []`` or ``x is {}`` will always evaluate to ``False``,
which is probably not the intended behavior.

Immutable Literals
~~~~~~~~~~~~~~~~~~

Because ``is`` detects equivalence under mutation, and immutable objects cannot
be mutated, it stands to reason that every equal immutable object could be
identical, as long as they are really *truly* equivalent. This is the approach
taken by PyPy, as well as the approach taken in e.g. JavaScript. To allow for
this, Python allows for immutable literals to be the same object. For example:

>>> 1e6 is 1e6
True

But Python also allows for them to *not* be the same object:

>>> x = 1e6
>>> x is 1e6
False

Whether the an identical immutable literal expression is the same object, or a
different but equal object, is implementation-defined. As a result, expressions
like ``x is ()``, ``x is 1.0``, ``x is 1``, ``x is b""``, or ``x is ""`` may
evaluate to either ``True`` or ``False``, or may even choose randomly between
the two. It is always incorrect to compare literals in this way, because of
the implementation-defined behavior.

Named Constants
~~~~~~~~~~~~~~~

``True``, ``False``, and ``None`` are not included in this rule: if a piece of
code should compare specifically against any of these three, it should use
``is``. They are *always* the same object, and ``x is None`` is not buggy.

``is`` for these values can be used to distinguish ``None`` or ``False`` from
values like ``0`` or ``[]``, and ``True`` from values like ``1`` or ``[1]``.
For bools, howver, this kind of explicit comparison is rare: most of the time
``x is True`` can be better phrased as just ``x``, and ``x is False`` can be
better phrased as ``not x``.

The Pedantic Section
--------------------

``x == y`` can't and doesn't *literally* mean that two objects are
interchangeable as long as you don't mutate them. For one thing, ``x is y`` may
evaluate to something different than ``y is y``.

A more complete definition would be something like: "are interchangeable as long
as you don't perform any identity-aware operations."

But even that is not enough, as anyone can define ``__eq__``. For example,
``mock.ANY`` compares equal to everything but is not equivalent to anything but
``mock.ANY``. And the designers of floating point numbers were particularly
cruel in defining a ``-0.0`` that compares equal to ``0.0``, but has subtly
different arithmetic behavior. And neither ``-0.0`` nor ``0.0`` can be used as
a list index, even though they both compare equal to ``0``, a valid list index.

There may be fewer things that follow the rule than that don't. But in some
spiritual sense, the idea behind ``==`` is interchangeability absent mutation
and other identity-centered operations, and the rest is practical shortcuts.
