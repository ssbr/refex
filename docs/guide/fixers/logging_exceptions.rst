Logging Exceptions
==================

Normally, none of the logging functions except :func:`logging.exception()`
include a stack trace. To include a stack trace, pass ``exc_info=True`` (e.g.
to log an exception + stack trace at a severity *less* than ``ERROR``), or
use :func:`logging.exception()`.

If there is a stack trace included, then the exception object itself is
redundant.

Example
-------

::

    try:
        ...
    except Exception as e:
        logging.error(e)
        ...

This might seem innocuous at first. It's not too uncommon to catch any exception
at the top of your request / event handling loop, log it, and move on. But if
you actually encounter an exception, what log message do you get? One example
might be::

    ERROR:root:0

Completely unhelpful! ``ERROR`` is the severity, ``root`` is the logger, and
``0`` could mean anything. In this case, maybe it was::

    {}[0]

Which raises a ``KeyError: 0``. But ``logging.error(e)`` doesn't include the
``KeyError``, because it's equivalent to ``logging.error(str(e))``, and
``str(e)`` does not include the type.

One way out, if you really don't want to include the stack trace, would be to
manually include the exception name::

    logging.error('%s: %s', type(e).__name_, e)

But since more information is better, it's more helpful to include the stack
trace::

    logging.error("", exc_info=True)
    # or:
    logging.exception("")

Since the error message is already included in the stack trace, the log message
should be something useful, rather than ``""`` or ``e``.
``logging.exception(e)`` is redundant, and ``logging.exception("")`` misses an
opportunity to provide context, specify what the inputs were, etc.
