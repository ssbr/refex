# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
""":mod:`~refex.python.matchers.syntax_matchers`
---------------------------------------------

High level pattern matchers on AST nodes.

These should be preferred to :mod:`~refex.python.matchers.ast_matchers`, as they
are safer and less brittle.

These are also available on the command line:

.. code-block: sh

    refex --mode=py.expr 'foo + $x' ...
    # equivalent: refex --mode=py 'ExprPattern("foo + $x")'

.. code-block: sh

    refex --mode=py.stmt 'foo = $x' ...
    # equivalent: refex --mode=py 'StmtPattern("foo = $x")'

Syntax
~~~~~~

Syntax patterns use ``$``-prefixed words as metavariables, where
that variable can stand for any syntax tree. For example, ``$x + 3`` matches
any addition operation where the right hand side is ``3``.

Additional restrictions can be placed on the tree using the ``restrictions``
parameter. For example, ``restrictions={'x': ExprPattern('4')}`` specifies
that ``$x`` is not a wildcard, but rather, only matches an ``ExprPattern(4)``.

.. warning::

    Patterns will match _exactly_ the same AST -- down to the order of
    members in a set. These patterns are still useful tools, but should be
    combined with other matchers to match exactly what you want.

        >>> list(matcher.find_iter(
        ...     ExprPattern('{1, 2}'),
        ...     matcher.parse_ast('{2, 1}')))  # fails
        []

Metavariables
~~~~~~~~~~~~~

Metavariables can be reused in a pattern, which constrains them to match an
equivalent AST (``BindConflict.MERGE_EQUIVALENT_AST``).

For example, ``[$x for $x in $y]`` will match ``[a for a in b]``, but not
``[a1 for a2 in b]``.

For convenience, these are rebound to normal ``Bind()`` variables outside of the
pattern matcher.

ExprPattern
~~~~~~~~~~~

.. autoclass:: ExprPattern

StmtPattern
~~~~~~~~~~~

.. autoclass:: StmtPattern
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import abc
import ast
import inspect
import itertools
import textwrap
import tokenize
import weakref

import attr
import cached_property
import six

from refex.python import matcher
from refex.python import python_pattern
from refex.python.matchers import ast_matchers
from refex.python.matchers import base_matchers


def _remap_macro_variables(pattern):
  """Renames the variables from the source pattern to give valid Python.

  Args:
    pattern: A source pattern containing metavariables like "$foo".

  Returns:
    (remapped_source, variables)
    * remapped_source is the pattern, but with all dollar-prefixed variables
      replaced with unique non-dollar-prefixed versions.
    * variables is the mapping of the original name to the remapped name.

  Raises:
    SyntaxError: The pattern can't be parsed.
  """
  remapped_tokens, metavar_indices = python_pattern.token_pattern(pattern)
  taken_tokens = {
      token[1]
      for i, token in enumerate(remapped_tokens)
      if i not in metavar_indices
  }
  original_to_unique = {}

  for metavar_index in metavar_indices:
    metavar_token = list(remapped_tokens[metavar_index])
    variable = metavar_token[1]

    if variable in original_to_unique:
      remapped_name = original_to_unique[variable]
    else:
      # the str calls are for b/115812866
      for suffix in itertools.chain([''], (str(i) for i in itertools.count())):
        # We need to add a prefix because e.g. if the variable was named
        # "__foo", it would get mangled inside a class body.
        # This also gives us a nice place to put the disambiguating counter
        # string.
        remapped_name = 'gensym%s_%s' % (suffix, variable)
        if remapped_name not in taken_tokens:
          taken_tokens.add(remapped_name)
          original_to_unique[variable] = remapped_name
          break
    metavar_token[1] = remapped_name
    remapped_tokens[metavar_index] = tuple(metavar_token)

  return tokenize.untokenize(remapped_tokens), original_to_unique


def _rewrite_submatchers(pattern, restrictions):
  """Rewrites pattern/restrictions to erase metasyntactic variables.

  Args:
    pattern: a pattern containing $variables.
    restrictions: a dictionary of variables to submatchers. If a variable is
      missing, Anything() is used instead.

  Returns:
    (remapped_pattern, variables, new_submatchers)
    * remapped_pattern has all variables replaced with new unique names that are
      valid Python syntax.
    * variables is the mapping of the original name to the remapped name.
    * new_submatchers is a dict from remapped names to submatchers. Every
      variable is put in a Bind() node, which has a submatcher taken from
      `restrictions`.

  Raises:
    KeyError: if restrictions has a key that isn't a variable name.
  """
  pattern, variables = _remap_macro_variables(pattern)
  incorrect_variables = set(restrictions) - set(variables)
  if incorrect_variables:
    raise KeyError('Some variables specified in restrictions were missing. '
                   'Did you misplace a "$"? Missing variables: %r' %
                   incorrect_variables)

  submatchers = {}
  for old_name, new_name in variables.items():
    submatchers[new_name] = base_matchers.Bind(
        old_name,
        restrictions.get(old_name, base_matchers.Anything()),
        on_conflict=matcher.BindConflict.MERGE_EQUIVALENT_AST,
    )

  return pattern, variables, submatchers


# TODO: Use a ast_matchers matcher.
# It'd be cute to use a ast_matchers matcher here, but matchers don't (yet) support
# giving detailed explanations for match failure.
# Something like this would be nice:
# return ast_matchers.Module(
#     body=base_matchers.ItemsAre([ast_matchers.Expr(value=Bind("expr"))])
# ).match_or_raise(expr)['expr']


def _pull_stmt(stmt):
  """Pulls the first stmt from an AST for a Python module."""
  if not isinstance(stmt, ast.Module):
    raise ValueError('statement/expression has unexpected type %r: %s' %
                     (type(stmt), ast.dump(stmt)))
  if len(stmt.body) != 1:
    raise ValueError(
        'statement/expression argument should have exactly 1 statement inside'
        ' of it, but has %d statements.' % len(stmt.body))
  return stmt.body[0]


def _pull_expr(expr):
  """Pull the first expr from an AST for a Python module.

  Args:
    expr: an ast.Module object containing exactly one statement, an Expr.

  Returns:
    The AST expression inside that Expr node.

  Raises:
    ValueError: if the ast module doesn't match the expected shape.
  """
  expr_node = _pull_stmt(expr)
  if not isinstance(expr_node, ast.Expr):
    raise ValueError(
        'expr argument should have an expression, not a statement: %s' %
        ast.dump(expr))
  return expr_node.value


def ast_matchers_matcher(tree):
  """Returns a matcher for _exactly_ this AST tree."""
  return _ast_pattern(tree, {})


def _ast_pattern(tree, variables):
  """Shared logic to compile an AST matcher recursively.

  Args:
    tree: the ast.expr/ast.stmt to match, or a list of ast nodes.
    variables: names to replace with submatchers instead of literally.

  Returns:
    A raw_aw matcher with any Name nodes from the variables map swapped out,
    as in ExprPattern.
  """
  # recursion isn't good because we can blow the stack for a ~1000-deep ++++foo,
  # but does that even happen IRL?
  # TODO: use a stack.
  if isinstance(tree, list):
    return base_matchers.ItemsAre([_ast_pattern(e, variables) for e in tree])
  if not isinstance(tree, ast.AST):
    # e.g. the identifier for an ast.Name.
    return base_matchers.Equals(tree)
  if isinstance(tree, ast.Name):
    if tree.id in variables:
      return variables[tree.id]
  return getattr(ast_matchers,
                 type(tree).__name__)(
                     **{
                         field: _ast_pattern(getattr(tree, field), variables)
                         for field in type(tree)._fields
                         # Filter out variable ctx.
                         if field != 'ctx' or not isinstance(tree, ast.Name)
                     })


def _verify_variables(tree, variables):
  """Raises ValueError if the variables are not present in the tree."""

  remapped_to_original = {v: k for k, v in variables.items()}

  found = set()

  class VariableVisitor(ast.NodeVisitor):

    def visit_Name(self, name):  # pylint: disable=invalid-name
      if name.id in remapped_to_original:
        found.add(remapped_to_original[name.id])

  VariableVisitor().visit(tree)
  missing = set(variables) - found
  # variables/remapped_to_original captures all $foo sequences we rewrote into
  # unique tokens. Each of those unique tokens was _supposed_ to get transformed
  # into a Name node for later processing, but apparently some were "lost".
  # e.g. foo.$bar does not produce a Name node for the $bar attribute, so we
  # can't find it. This results in patterns that are not what the author
  # intended
  # TODO(b/117837631): Allow foo.$bar somehow
  if missing:
    raise ValueError(
        'https://refex.readthedocs.io/en/latest/guide/errors/nonname_metavariables.html'
        ' : The following metavariables were not found in the AST: {%s}' %
        ', '.join(sorted(missing)))


@attr.s(frozen=True)
class _BaseAstPattern(matcher.Matcher):
  """Base class for AST patterns.

  Subclasses should implement a _pull_ast(module_ast) method which returns the
  AST to match from that module.
  """

  # store the init parameters for a pretty repr.
  pattern = attr.ib()  # type: Text
  restrictions = attr.ib(
      default=attr.Factory(dict))  # type: Dict[Text, matcher.Matcher]

  _ast_matcher = matcher.submatcher_attrib(
      repr=False,
      init=False,
      default=attr.Factory(
          lambda self: self._get_matcher(),  # pylint: disable=protected-access
          takes_self=True),
  )  # type: matcher.Matcher

  def _get_matcher(self):
    try:
      remapped_pattern, variable_names, variables = _rewrite_submatchers(
          self.pattern, self.restrictions)
      parsed_ast = ast.parse(remapped_pattern)
    except SyntaxError as e:
      raise ValueError('Failed to parse %r: %s' % (self.pattern, e))
    _verify_variables(parsed_ast, variable_names)
    intended_match_ast = self._pull_ast(parsed_ast)
    return base_matchers.Rebind(
        _ast_pattern(intended_match_ast, variables),
        on_conflict=matcher.BindConflict.MERGE,
        on_merge=matcher.BindMerge.KEEP_LAST,
    )

  @abc.abstractmethod
  def _pull_ast(self, module_ast):
    """Given an ast.Module, returns the AST to match precisely."""
    raise NotImplementedError  # not MI friendly, but whatever.

  def _match(self, context, candidate):
    return self._ast_matcher.match(context, candidate)


@matcher.safe_to_eval
class ExprPattern(_BaseAstPattern):
  """An AST matcher for a pattern expression.

  `ExprPattern` creates a matcher that exactly matches a given AST, but also
  allows placeholders. For example, this will match any addition of two
  variables
  named literally foo and bar::

      ExprPattern('foo + bar')

  But this will match any addition expression at all::

      ExprPattern('$foo + $bar')

  In addition, whatever expressions $foo or $bar matched will be a bound
  variable
  in the match (under 'foo' and 'bar').

  Args:
    pattern: The pattern to match, an expression.
    restrictions: (*optional*) A dict mapping metavariables to matchers.
  """

  _pull_ast = staticmethod(_pull_expr)


@matcher.safe_to_eval
class StmtPattern(_BaseAstPattern):
  """An AST matcher for a pattern statement.

  :class:`StmtPattern` is like :class:`ExprPattern`, but for an entire (single)
  statement!

  Like :class:`ExprPattern`, :class:`StmtPattern` creates a matcher that exactly
  matches a given AST, but also allows placeholders. For example, this will
  match any assignment where the literal variable ``foo`` is set to the literal
  variable ``bar``::

      StmtPattern('foo = bar')

  But this will match any assignment statement at all::

      StmtPattern('$foo = $bar'}

  Args:
    pattern: The pattern to match, a statement.
    restrictions: (*optional*) A dict mapping metavariables to matchers.
  """

  _pull_ast = staticmethod(_pull_stmt)


@attr.s(frozen=True)
class StmtFromFunctionPattern(matcher.Matcher):
  """A StmtPattern, but using a function to define the syntax.

  Instead of using metavars with `$`, they must be defined in the function
  arguments. So for example::

      def before(foo):
        foo.bar = 5

      matcher = StmtFromFunctionPattern(before)

  is equivalent to::

      StmtPattern('$foo.bar = 5')

  This makes it much more obvious that patterns like the following will not work
  as expected::

      def before(x):
        import x

  FunctionPatterns may, optionally, include a docstring describing what the
  pattern should match. This will be ignored by the matcher. The name of the
  function is arbitrary, but metavar names must be defined in the function
  arguments.

  FunctionPatterns are resolved using `inspect.getsource`. This leads to a few
  limitations, importantly the functions used cannot be lambdas, and the matcher
  will fail (with weird errors) if you attempt to define and use a FromFunction
  matcher in an interactive session or other situations where source code isn't
  accessible.
  """
  func = attr.ib()  # type: Callable

  _ast_matcher = matcher.submatcher_attrib(
      repr=False,
      init=False,
      default=attr.Factory(
          lambda self: self._get_matcher(),  # pylint: disable=protected-access
          takes_self=True),
  )  # type: matcher.Matcher

  def _get_matcher(self):
    """Override of get_matcher to pull things from a function object."""
    # `inspect.getsource` doesn't, say, introspect the code object for its
    # source. Python, despite its dyanamism, doesn't support that much magic.
    # Instead, it gets the file and line number information from the code
    # object, and returns those lines as the source. This leads to a few
    # interesting consequences:
    #   - Functions that exist within a class or closure are by default
    #     `IndentationError`, the code block must be textwrap-dedented before
    #     being used.
    #   - This won't work in interactive modes (shell, ipython, etc.)
    #   - Functions are normally statements, so treating everything from the
    #     first line to the last as part of the function is probably fine. There
    #     are a few cases where this will break, namely
    #      - A lambda will likely be a syntax error, the tool will see
    #        `lambda x: x)`, where `)` is the closing paren of the enclosing
    #        scope.
    source = textwrap.dedent(inspect.getsource(self.func))
    args = _args(self.func)
    try:
      parsed = ast.parse(source)
    except SyntaxError:
      raise ValueError('Function {} appears to have invalid syntax. Is it a'
                       ' lambda?'.format(self.func.__name__))
    actual_body = parsed.body[0].body
    if (isinstance(actual_body[0], ast.Expr) and
        isinstance(actual_body[0].value, ast.Str)):

      # Strip the docstring, if it exists.
      actual_body = actual_body[1:]
    if not actual_body:
      raise ValueError('Format function must include an actual body, a '
                       'docstring alone is invalid.')
    if isinstance(actual_body[0], ast.Pass):
      raise ValueError('If you *really* want to rewrite a function whose body '
                       'is just `pass`, use a regex replacer.')
    # Since we don't need to mangle names, we just generate bindings.
    bindings = {}
    for name in args:
      bindings[name] = base_matchers.Bind(
          name,
          base_matchers.Anything(),
          on_conflict=matcher.BindConflict.MERGE_EQUIVALENT_AST)
    return base_matchers.Rebind(
        _ast_pattern(actual_body[0], bindings),
        on_conflict=matcher.BindConflict.MERGE,
        on_merge=matcher.BindMerge.KEEP_LAST,
    )

  def _match(self, context, candidate):
    return self._ast_matcher.match(context, candidate)


class ModulePattern(_BaseAstPattern):
  """An AST matcher for an entire module.

  Unlike ExprPattern and StmtPattern, it matches the sequence of statements,
  expressions, etc. within the entire module, and not somewhere within the
  module.

  This is a lower level tool meant for implementing other matchers and tools by
  creating an AST equality checker, so it is not exposed to matcher users.
  """

  _pull_ast = staticmethod(lambda tree: tree)


# TODO: Something that can match multiple statements, that isn't
# ModulePattern. For example, imagine writing a matcher that could find this:
#
#    def foo(): pass
#    foo = bar(foo)
#
# And replace it with this:
#
#    @bar
#    def foo(): pass


def _ast_children(candidate):
  """Yields all children of an AST node, broadly defined as an AST or list."""
  if isinstance(candidate, ast.AST):
    for field in candidate._fields:
      try:
        yield getattr(candidate, field)
      except AttributeError:
        continue
  elif isinstance(candidate, list):
    for item in candidate:
      yield item


@matcher.safe_to_eval
@attr.s(frozen=True)
class HasParent(matcher.Matcher):
  """Matches an AST node if its direct parent matches the submatcher.

  An AST node in this context is considered to be an AST object or a list
  object. Only direct parents are yielded -- the exact object x s.t. the
  candidate is `x.y` or `x[y]`, for some y. There is no recursive traversal of
  any kind.

  Fails the match if the candidate node is not an AST object or list.
  """
  _submatcher = matcher.submatcher_attrib()

  def _match(self, context, candidate):
    parent = context.parsed_file.nav.get_parent(candidate)
    if parent is None:
      return None
    m = self._submatcher.match(context, parent)
    if m is None:
      return None
    return matcher.MatchInfo(
        matcher.create_match(context.parsed_file, candidate), m.bindings)


@matcher.safe_to_eval
@attr.s(frozen=True)
class IsOrHasAncestor(matcher.Matcher):
  """Matches a candidate if it or any ancestor matches the submatcher.

  If the candidate directly matches, then that match is returned. Otherwise,
  the candidate is recursively traversed using HasParent until a match is found.
  """
  _submatcher = matcher.submatcher_attrib()

  @cached_property.cached_property
  def _recursive_matcher(self):
    return base_matchers.RecursivelyWrapped(self._submatcher, HasParent)

  def _match(self, context, candidate):
    return self._recursive_matcher.match(context, candidate)


@matcher.safe_to_eval
@attr.s(frozen=True)
class HasAncestor(matcher.Matcher):
  """Matches an AST node if any ancestor matches the submatcher.

  This is equivalent to HasParent(IsOrHasAncestor(...)).
  """
  _submatcher = matcher.submatcher_attrib()

  @cached_property.cached_property
  def _recursive_matcher(self):
    return HasParent(IsOrHasAncestor(self._submatcher))

  def _match(self, context, candidate):
    return self._recursive_matcher.match(context, candidate)


@matcher.safe_to_eval
@attr.s(frozen=True)
class HasChild(matcher.Matcher):
  """Matches an AST node if a direct child matches the submatcher.

  An AST node in this context is considered to be an AST object or a list
  object. Only direct children are yielded -- `AST.member` or `list[index]`.
  There is no recursive traversal of any kind.

  Fails the match if the candidate node is not an AST object or list.
  """
  _submatcher = matcher.submatcher_attrib()

  def _match(self, context, candidate):
    for child in _ast_children(candidate):
      m = self._submatcher.match(context, child)
      if m is None:
        continue
      return matcher.MatchInfo(
          matcher.create_match(context.parsed_file, candidate), m.bindings)
    return None


@matcher.safe_to_eval
@attr.s(frozen=True)
class IsOrHasDescendant(matcher.Matcher):
  """Matches a candidate if it or any descendant matches the submatcher.

  If the candidate directly matches, then that match is returned. Otherwise,
  the candidate is recursively traversed using HasChild until a match is found.
  """
  _submatcher = matcher.submatcher_attrib()

  @cached_property.cached_property
  def _recursive_matcher(self):
    return base_matchers.RecursivelyWrapped(self._submatcher, HasChild)

  def _match(self, context, candidate):
    return self._recursive_matcher.match(context, candidate)


@matcher.safe_to_eval
@attr.s(frozen=True)
class HasDescendant(matcher.Matcher):
  """Matches an AST node if any descendant matches the submatcher.

  This is equivalent to HasChild(IsOrHasDescendant(...)).
  """
  _submatcher = matcher.submatcher_attrib()

  @cached_property.cached_property
  def _recursive_matcher(self):
    return HasChild(IsOrHasDescendant(self._submatcher))

  def _match(self, context, candidate):
    return self._recursive_matcher.match(context, candidate)


@attr.s(frozen=True)
class HasFirstAncestor(matcher.Matcher):
  """The first ancestor to match `first_ancestor` also matches `also_matches`.

  For example, "the function that I am currently in is a generator function" is
  a matcher that one might want to create, and can be created using
  HasFirstAncestor.
  """
  _first_ancestor = matcher.submatcher_attrib()
  _also_matches = matcher.submatcher_attrib()

  def _match(self, context, candidate):
    parent = candidate
    while True:
      parent = context.parsed_file.nav.get_parent(parent)
      if parent is None:
        return None

      m = self._first_ancestor.match(context, parent)
      if m is not None:
        break

    ancestor = m.match.matched
    m2 = self._also_matches.match(context, ancestor)
    if m2 is None:
      return None
    return matcher.MatchInfo(
        matcher.create_match(context.parsed_file, candidate),
        matcher.merge_bindings(m.bindings, m2.bindings))


@matcher.safe_to_eval
@attr.s(frozen=True)
class HasPrevSibling(matcher.Matcher):
  """Matches a node if the immediate prior sibling in the node list matches submatcher."""
  _submatcher = matcher.submatcher_attrib()

  def _match(self, context, candidate):
    sibling = context.parsed_file.nav.get_prev_sibling(candidate)
    if sibling:
      return self._submatcher.match(context, sibling)
    return None


@matcher.safe_to_eval
@attr.s(frozen=True)
class HasNextSibling(matcher.Matcher):
  """Matches a node if the immediate next sibling in the node list matches submatcher."""
  _submatcher = matcher.submatcher_attrib()

  def _match(self, context, candidate):
    sibling = context.parsed_file.nav.get_next_sibling(candidate)
    if sibling:
      return self._submatcher.match(context, sibling)
    return None


@matcher.safe_to_eval
@attr.s(frozen=True)
class NamedFunctionDefinition(matcher.Matcher):
  """A matcher for a named function definition.

  In Python 3, this includes both regular functions and async functions.

  Constructor arguments:
    body: The matcher for the function body.
    returns: The matcher for the return type annotation. Ignored on Python 2.
  """

  _body = matcher.submatcher_attrib(default=base_matchers.Anything())
  _returns = matcher.submatcher_attrib(default=base_matchers.Anything())

  @cached_property.cached_property
  def _matcher(self):
    kwargs = {'body': self._body}
    # We check for the existence of `returns` as an AST field, instead of
    # checking the Python version, to support backports of the type annotation
    # syntax to Python 2.
    if 'returns' in attr.fields_dict(ast_matchers.FunctionDef):
      kwargs['returns'] = self._returns
    function_def = ast_matchers.FunctionDef(**kwargs)
    if six.PY3:
      function_def = base_matchers.AnyOf(
          ast_matchers.AsyncFunctionDef(**kwargs),
          function_def,
      )
    return function_def

  def _match(self, context, candidate):
    return self._matcher.match(context, candidate)


@matcher.safe_to_eval
@attr.s(frozen=True)
class InNamedFunction(matcher.Matcher):
  """Matches anything directly inside of a function that matches `submatcher`."""
  _submatcher = matcher.submatcher_attrib()

  @cached_property.cached_property
  def _recursive_matcher(self):
    return HasFirstAncestor(
        first_ancestor=NamedFunctionDefinition(), also_matches=self._submatcher)

  def _match(self, context, candidate):
    return self._recursive_matcher.match(context, candidate)


@matcher.safe_to_eval
@attr.s(frozen=True)
class WithTopLevelImport(matcher.Matcher):
  """Matches an AST node if there is a top level import for the given module.

  Constructor arguments:

    submatcher: The matcher to filter results from.
    module_name: The fully-qualified module name as a string. e.g. 'os.path'.
    as_name: The variable name the module is imported as.
      Defaults to the name one would get from e.g. 'from os import path'.
  """
  # TODO: Would be nice to match on function-local imports as well.
  # TODO: Would be nice to use submatchers for module_name/as_name.
  _submatcher = matcher.submatcher_attrib()

  _module_name = attr.ib()
  _as_name = attr.ib()

  @_as_name.default
  def _as_name_default(self):
    return self._module_name.rsplit('.', 1)[-1]

  # per-AST state
  _ast_imports = weakref.WeakKeyDictionary()

  @classmethod
  def _get_ast_imports(cls, tree):
    if tree not in cls._ast_imports:
      cls._ast_imports[tree] = _top_level_imports(tree)
    return cls._ast_imports[tree]

  def _match(self, context, candidate):
    imports = self._get_ast_imports(context.parsed_file.tree)
    if (self._module_name in imports and
        imports[self._module_name] == self._as_name):
      return self._submatcher.match(context, candidate)
    return None


def _top_level_imports(tree):
  """Returns dict of module names to variable names for top-level imports.

  For example, 'from os import path' leads to {'os.path': 'path'}.

  Args:
    tree: An ast.Module.

  Returns:
    The top level imports as a dict from module name to variable name.
  """
  imports = {}
  for stmt in tree.body:
    if isinstance(stmt, ast.Import):
      for alias in stmt.names:
        if alias.asname is None:
          imported_module = alias.name.split('.', 1)[0]
          imports[imported_module] = imported_module
        else:
          imports[alias.name] = alias.asname
    elif isinstance(stmt, ast.ImportFrom):
      if stmt.level != 0:
        # TODO: This should understand "from .foo import bar" imports,
        # This requires knowing what package we are currently in, which is hard
        # due to some environments that don't even require an __init__.py :C
        # (for example, namespace packages.)
        continue
      for alias in stmt.names:
        if alias.asname is None:
          as_name = alias.name
        else:
          as_name = alias.asname
        imported_module = '.'.join([stmt.module, alias.name])
        imports[imported_module] = as_name
  return imports


def _args(f):
  if six.PY2:
    return inspect.getargspec(f)[0]
  else:
    return list(inspect.signature(f).parameters.keys())
