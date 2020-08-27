Python Patterns and Templates
=============================

Refex offers in several places the ability to provide a python-like
pattern or template with metavariables like ``$foo``:

 * ``--mode=py.expr`` and ``--mode=py.stmt`` on the command line.
 * :class:`~refex.python.matchers.syntax_matchers.ExprPattern` and
   :class:`~refex.python.matchers.syntax_matchers.StmtPattern` with
   ``--mode=py`` or when using :mod:`refex.python.matchers.syntax_matchers`
   directly.

These are parsed as Python code (except for the ``$metavariables``, of course),
and let you specify an AST matcher by example. They are in many ways a
shallow layer on top of writing out an AST by hand using
:mod:`~refex.python.matchers.ast_matchers`.

Rules:

 * A metavariable is any variable name preceded by a ``$``.

 * A metavariable can only be placed anywhere in the pattern that a Python
   ``ast.Name`` AST node is valid. For example, ``$foo.bar`` is OK, but
   ``foo.$bar`` is not.

 * A metavariable matches any AST.

 * If the same metavariable occurs twice in a pattern, each place must match
   a structurally identical AST, following the same rules as pattern
   matching without metavariables.

 * A variable name pattern always matches the same variable name in the target,
   even if one is an rvalue (i.e. used in an expression) and the other is an
   lvalue (i.e. used as the target of an assignment).

   For example, ``a`` matches twice in ``a = a``.

 * Otherwise, a pattern matches structurally in the obvious way (e.g.
   ``a1 + b1`` matches ``a2 + b2`` if ``a1`` matches ``a2``, and ``b1`` matches
   ``b2``.)

   .. important:: This is purely syntactic. ``{a, b}`` does not match
      ``{b, a}``.

 * Comments are completely ignored in both the template and the target.

There is currently no support for n-ary wildcards, like ``{a, $..., b}``.

Templates
---------

Templates are syntactically identical to patterns, but represent the opposite
direction: instead of an AST to match, they describe an AST to create.

Rules:

 * Syntactically, templates are identical to patterns. (e.g. metavariables
   can only occur where an ``ast.Name`` could.

 * The result of substitution into a template will always be structurally
   identical to that template. In other words, if the template were
   reinterpreted as a pattern, it would always match the substitution result.

   For example, rendering ``$a * 3`` with a = ``1 + 2`` results in
   ``(1 + 2) * 3``. Parentheses are inserted as necessary.
