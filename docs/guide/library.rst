Using Refex as a Library
========================

Alright, your one-line shell script change isn't enough anymore. What's next?

Create a searcher
-----------------

The "thing that does a search and a replace" is a searcher: any subclass of
:class:`refex.search.AbstractSearcher`. You likely want
:class:`~refex.search.PyExprRewritingSearcher`, and, for the replacement, an
instance of :class:`refex.python.syntactic_template.PythonExprTemplate`.

This ends up a bit clunky, but you can see how it works in the example at the
bottom of the page.

If you want to manipulate, filter, or otherwise look at the replacements
being performed, this is where you can hook in: define a new searcher that
wraps the old one and modifies its results.

Execute the search / replace
----------------------------

Apply a searcher to a string
............................

:func:`refex.search.rewrite_string()` executes a simple rewrite.

Alternatively, you can collect a list of
:class:`~refex.substitution.Substitution` objects and apply them in a second
pass, using :func:`refex.search.find_iter()` and
:func:`refex.formatting.apply_substitutions()` -- but really, it's better
to manipulate those substitutions from a custom searcher, since that
searcher can also be used e.g. to create an executable, as the section below
describes.

Create an executable
....................

The same colorization, diff display, etc. as the :command:`refex` command can
be yours: instead of rewriting individual strings, you can pass the searcher
to :func:`refex.cli.run`.

Here's a complete example:

.. literalinclude:: /../examples/example_binary.py
   :lines: 14-
