Mutable Constants
=================

Mutable globals that *look* like immutable constants (e.g. following
``ALL_CAPS`` naming convention) can lead to hard-to-find bugs. If possible, it's
better to use an immutable global instead.

**Alternatives:**

+----------+-------------------------------------------------------------------+
| Before   | After                                                             |
+==========+===================================================================+
| ``list`` | ``tuple``                                                         |
+----------+-------------------------------------------------------------------+
| ``set``  | ``frozenset``                                                     |
+----------+-------------------------------------------------------------------+
| ``dict`` | frozendict_                                                       |
|          |                                                                   |
|          | See also: `PEP 603`_; `PEP 416`_                                  |
+----------+-------------------------------------------------------------------+

.. _frozendict: https://pypi.org/project/frozendict/
.. _PEP 603: https://www.python.org/dev/peps/pep-0603/
.. _PEP 416: https://www.python.org/dev/peps/pep-0416/
