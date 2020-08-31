Non-Name Metavariables
===============================================

.. TODO: b/117837631 tracks fixing this.

Metavariables can only occur where ``ast.Name`` nodes can occur in the AST.
For example, ``$foo.bar`` works because ``foo.bar`` is a valid expression where
``foo`` is a ``Name`` node.

.. TODO: less harsh highlighting of good/bad

Works::

    $foo.attr
    $foo + 3

.. error::

    Doesn't work::

        obj.$foo
        def $foo(): pass
        import $foo as $bar

When debugging this error message, it can help to use :func:`ast.dump` with
every ``$`` removed to see if the AST produces a ``Name`` node there. For
example, when debugging why ``obj.$foo`` or ``import $foo`` won't work, we could
print these ASTs:

    >>> import ast
    >>> print(ast.dump(ast.parse('obj.foo').body[0]))
    Expr(value=Attribute(value=Name(id='obj', ctx=Load()), attr='foo', ctx=Load()))

    >>> print(ast.dump(ast.parse('import foo').body[0]))
    Import(names=[alias(name='foo', asname=None)])


We can see from this the place we wanted to use a metavariable is not a ``Name``
node (``attr='foo'``, ``name='foo'``). These places cannot be matched using
metavariables in a pattern.

For more about metavariables and Python patterns, see
:doc:`/guide/patterns_templates`.