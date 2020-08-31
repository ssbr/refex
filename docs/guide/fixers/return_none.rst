How To Return None
==================

`PEP-8 <https://www.python.org/dev/peps/pep-0008/>`_ offers guidance on how to
return ``None`` ("Be consistent in return statements. [...]"), which can be
slightly extended into the following rules of thumb:

* If a function only returns ``None``, only "bare returns" (a ``return``
  statement with no return expression or value) should be used, and only to
  return early.

* If a function returns ``Optional[...]``, then all code paths should have a
  non-bare ``return`` statement.
