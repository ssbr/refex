Parentheses around a single variable in string formatting
=========================================================

Parentheses around a single item in Python has no effect: ``(foo)`` is exactly
equivalent to ``foo``. In many cases this is harmless, but it can suggest a
subtle bug when used in string formatting. A '`%`'-formatted string with a
single format specifier can be formatted using a single value or a one element
tuple: ``'hello %s' % name`` or ``'hello %s' % (name,)``. The latter is safer if
there's a chance the `name` variable could itself be a tuple:

.. code-block::
   :emphasize-lines: 7

    name = 'World'
    'hello %s' % (name,)  # "hello World"
    'hello %s' % name  # "hello World"

    name = ('World', 'Universe')
    'hello %s' % (name,)  # "hello ('World', 'Universe')
    'hello %s' % name  # TypeError: not all arguments converted during string formatting

Consequently, a line like ``error_msg = 'Cannot process %s' % (data)`` may leave
code reviewers and future readers unsure if there is a subtle bug if ``data`` is
a tuple. Did the author *mean* to write ``(data,)`` but forgot the comma? Prefer
to be explicit in these cases: Either drop the parentheses or add a comma.
