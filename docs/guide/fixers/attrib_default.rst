Mutable defaults in :func:`attr.ib()`
=====================================

Mutable defaults to passed to :func:`attr.ib` should always be specified as
factories instead.

Attributes defined using ``attrs`` share the default value across all
instantiations, unless another value is passed. For example:

.. caution::

   .. code-block::

        import attr
        @attr.s
        class A(object):
          x = attr.ib(default=[])

        a1 = A()
        a2 = A()

        a1.x.append(0)
        print(a2.x) # Output: [0]

``attrs`` lets users work around this by specifying a *factory* which
is called on every instantiation, instead of a *default*, which is evaluated
only once, at class definition time. The most general way to specify this is
with :class:`attr.Factory`, but for simple cases, it is easier to pass a
callback to the ``factory`` parameter::

    class B(object):
      x = attr.ib(factory=list)

    b1 = B()
    b2 = B()

    b1.x.append(0)
    print(b2.x) # Output: []


Any argument which is mutable, and any argument which can change over time,
should as a rule be passed as a factory. Exceptions should be shockingly rare,
and documented clearly.
