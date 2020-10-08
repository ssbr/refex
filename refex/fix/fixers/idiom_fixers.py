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
"""Fixers for making code clearer and more Pythonic.

These are most of all useful as combining fixers for less trivial changes, via
https://refex.readthedocs.io/en/latest/guide/fixers/merged.html
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals  # for convenience

import textwrap

from refex import formatting
from refex import future_string
from refex.fix import fixer
from refex.python import matcher as matcher_
from refex.python import syntactic_template
from refex.python.matchers import ast_matchers
from refex.python.matchers import base_matchers
from refex.python.matchers import syntax_matchers

_MUTABLE_CONSTANT_CATEGORY = 'idioms.mutable-constant'
_NONE_RETURNS_CATEGORY = 'idioms.none-return'
_LOGGING_EXCEPTION_CATEGORY = 'idioms.logging.exception'
_CONSTANT_MATCHER = base_matchers.MatchesRegex(r'[A-Z_\d]+')


def idiom_fixer(
    old_expr,
    new_expr,
    category,
    url='https://refex.readthedocs.io/en/latest/guide/fixers/idiom.html',
):
  """Fixer for making expressions "clearer" / less convoluted.

  This also helps normalize them for other fixers to apply.

  Args:
    old_expr: An ExprPattern string for the expr to match.
    new_expr: A string.Template string for the replacement.
    category: A category for the fix.
    url: An URL describing the fix.

  Returns:
    A fixer that replaces old_expr with new_expr.
  """
  dotdotdot = fixer.ImmutableDefaultDict(lambda _: '...')
  return fixer.SimplePythonFixer(
      message=('This could be more Pythonic: %s -> %s.' %
               ((future_string.Template(old_expr).substitute(dotdotdot),
                 future_string.Template(new_expr).substitute(dotdotdot)))),
      matcher=syntax_matchers.ExprPattern(old_expr),
      replacement=syntactic_template.PythonExprTemplate(new_expr),
      url=url,
      significant=False,
      category=category,
  )


def _mutable_constant_fixer(matcher, replacement, **kwargs):
  return fixer.SimplePythonFixer(
      message='For constants, prefer immutable collections (like frozensets or tuples) to mutable collections (like sets or lists).',
      url='https://refex.readthedocs.io/en/latest/guide/fixers/mutable_constants.html',
      significant=False,
      category=_MUTABLE_CONSTANT_CATEGORY,
      matcher=matcher,
      replacement=replacement,
      **kwargs)


def _function_containing(matcher):
  """Returns a ast_matchers matcher for a function where any statement in the body matches `matcher`."""
  return syntax_matchers.NamedFunctionDefinition(
      body=base_matchers.Contains(syntax_matchers.IsOrHasDescendant(matcher)))


# Matches any function returning Optional[T] for some T.
_IN_FUNCTION_RETURNING_OPTIONAL = syntax_matchers.InNamedFunction(
    syntax_matchers.NamedFunctionDefinition(
        returns=base_matchers.AnyOf(
            syntax_matchers.ExprPattern('Optional[$_]'),
            syntax_matchers.ExprPattern('typing.Optional[$_]'),
            # TODO: May want to also include Union[None, ...].
            # TODO: match type comments as well.
        )))

# Matches any returning that's not "return" or "return None" (which are two
# different ast node values: ast.Return(value=None) and
# ast.Return(value=ast.Name(id='None')) respectively)
_NON_NONE_RETURN = matcher_.DebugLabeledMatcher(
    'Non-none return',
    ast_matchers.Return(
        value=base_matchers.Unless(
            base_matchers.AnyOf(
                base_matchers.Equals(None), syntax_matchers.ExprPattern(
                    'None')))))

_NONE_RETURNS_FIXERS = [
    fixer.SimplePythonFixer(
        message='If a function ever returns a value, all the code paths should have a return statement with a return value.',
        url='https://refex.readthedocs.io/en/latest/guide/fixers/return_none.html',
        significant=False,
        category=_NONE_RETURNS_CATEGORY,
        matcher=base_matchers.AllOf(
            syntax_matchers.StmtPattern('return'),
            syntax_matchers.InNamedFunction(
                _function_containing(_NON_NONE_RETURN)),
            # Nested functions are too weird to consider right now.
            # TODO: Add matchers to match only the first ancestor
            # function and a way to use IsOrHasDescendant that doesn't recurse
            # into nested functions.
            base_matchers.Unless(
                syntax_matchers.InNamedFunction(
                    _function_containing(
                        syntax_matchers.NamedFunctionDefinition())))),
        replacement=syntactic_template.PythonStmtTemplate('return None'),
        example_fragment=textwrap.dedent("""
            def f(x):
              if x:
                return
              return -1
            """),
        example_replacement=textwrap.dedent("""
            def f(x):
              if x:
                return None
              return -1
            """),
    ),
    fixer.SimplePythonFixer(
        message='If a function never returns a value other than None, only a "bare return" should be used.',
        url='https://refex.readthedocs.io/en/latest/guide/fixers/return_none.html',
        significant=False,
        category=_NONE_RETURNS_CATEGORY,
        matcher=base_matchers.AllOf(
            syntax_matchers.StmtPattern('return None'),
            base_matchers.Unless(
                syntax_matchers.InNamedFunction(
                    _function_containing(_NON_NONE_RETURN))),
            base_matchers.Unless(_IN_FUNCTION_RETURNING_OPTIONAL),
            base_matchers.Unless(
                syntax_matchers.InNamedFunction(
                    _function_containing(
                        syntax_matchers.NamedFunctionDefinition())))),
        replacement=syntactic_template.PythonStmtTemplate('return'),
        # We choose an example fragment that is short enough to demonstrate the
        # fix but not so contrived that it could obviously be rewritten
        # using different logic.
        example_fragment=textwrap.dedent("""
            def f(x):
              if x:
                print("first")
                return
              elif y:
                print("second")
                return None
              print("third")
            """),
        example_replacement=textwrap.dedent("""
            def f(x):
              if x:
                print("first")
                return
              elif y:
                print("second")
                return
              print("third")
            """),
    )
]

_MUTABLE_CONSTANT_FIXERS = (
    # Users used to Python2 might expect the replacement to be frozenset([...]).
    # That idiom predates set literals. In Python 3, the repr of frozenset, and
    # the idiom for producing frozensets, changed to frozenset({...}).
    _mutable_constant_fixer(
        matcher=syntax_matchers.StmtPattern(
            '$constant = $set',
            dict(constant=_CONSTANT_MATCHER, set=ast_matchers.Set())),
        replacement=syntactic_template.PythonStmtTemplate(
            '$constant = frozenset($set)'),
        example_fragment='FOO_BAR = {1, 2, 3}',
        example_replacement='FOO_BAR = frozenset({1, 2, 3})',
    ),
    # TODO: Rewrite to `frozenset(x for x in y)` instead of
    # `frozenset({x for x in y})`. In order to do that we need to bind a
    # variable to the `generators` field of `SetComp`, and then use that in a
    # template.
    _mutable_constant_fixer(
        matcher=syntax_matchers.StmtPattern(
            '$constant = $setcomp',
            dict(constant=_CONSTANT_MATCHER, setcomp=ast_matchers.SetComp())),
        replacement=syntactic_template.PythonStmtTemplate(
            '$constant = frozenset($setcomp)'),
        example_fragment='_BAZ = {x for x in y()}',
        example_replacement='_BAZ = frozenset({x for x in y()})',
    ),
    _mutable_constant_fixer(
        matcher=syntax_matchers.StmtPattern('$constant = set($iterable)',
                                            dict(constant=_CONSTANT_MATCHER)),
        replacement=syntactic_template.PythonStmtTemplate(
            '$constant = frozenset($iterable)'),
        example_fragment='_FOO1_BAZ2 = set(my_mod.my_func())',
        example_replacement='_FOO1_BAZ2 = frozenset(my_mod.my_func())',
    ),
    # TODO(b/147293349): Fix only sets that are never mutated (and enable the
    # below fixer).

    # Most cases of a "CONSTANT" assigned to an empty set seem to be cases where
    # the set itself is later modified. Some of those modifications can likely
    # be moved into the definition, but others mean the constant should be
    # renamed.
    #
    # _mutable_constant_fixer(
    #   matcher=syntax_matchers.StmtPattern('$constant = set()',
    #                                       dict(constant=_CONSTANT_MATCHER)),
    #   replacement=syntactic_template.PythonStmtTemplate(
    #                                        '$constant = frozenset()'),
    #   example_fragment='_FOO1_BAZ2 = set()',
    #   example_replacement='_FOO1_BAZ2 = frozenset()',
    # ),
)

_NEGATION_CATEGORY = 'pylint.g-comparison-negation'
_UNNECESSARY_COMPREHENSION_CATEGORY = 'idioms.uncessary-comprehension'

_Try = getattr(ast_matchers, 'Try', getattr(ast_matchers, 'TryExcept', None))  # type alias; pylint: disable=invalid-name


def _in_exception_handler(identifier, on_conflict):
  """Returns a matcher for a node in the nearest ancestor `except` & binds `identifier`.

  Args:
    identifier: Name of variable to bind the identifier in the nearest ancestor
      exception handler to
    on_conflict: BindConflict strategy for binding the identifier
  """
  return syntax_matchers.HasFirstAncestor(
      ast_matchers.ExceptHandler(),
      ast_matchers.ExceptHandler(
          name=base_matchers.AnyOf(
              # In PY2, the name is a `Name` but in PY3 just a
              # string.
              # So rather than capturing and merging the Name
              # nodes, we capture and merge the actual string
              # identifier.
              ast_matchers.Name(
                  id=base_matchers.Bind(identifier, on_conflict=on_conflict)),
              base_matchers.Bind(identifier, on_conflict=on_conflict),
          )))


_LOGGING_FIXERS = (
    fixer.SimplePythonFixer(
        message='Use logging.exception inside an except handler to automatically log the full stack trace of the error',
        url='https://refex.readthedocs.io/en/latest/guide/fixers/logging_exceptions.html',
        significant=True,
        category=_LOGGING_EXCEPTION_CATEGORY,
        matcher=base_matchers.AllOf(
            ast_matchers.Call(
                func=base_matchers.Bind(
                    'logging_error',
                    syntax_matchers.ExprPattern('logging.error')),
                args=base_matchers.Contains(
                    base_matchers.AllOf(
                        _in_exception_handler(
                            'e',
                            on_conflict=matcher_.BindConflict.MERGE_IDENTICAL),
                        ast_matchers.Name(
                            id=base_matchers.Bind(
                                'e',
                                on_conflict=matcher_.BindConflict
                                .MERGE_IDENTICAL)))),
                keywords=base_matchers.Unless(
                    base_matchers.Contains(
                        ast_matchers.keyword(arg='exc_info'))),
            ),),
        replacement=dict(
            logging_error=syntactic_template.PythonStmtTemplate(
                'logging.exception')),
        example_fragment=textwrap.dedent("""
          try:
            x = bar() + baz()
          except KeyError as e:
            logging.error('Bad thing happened: %s', e)
            """),
        example_replacement=textwrap.dedent("""
          try:
            x = bar() + baz()
          except KeyError as e:
            logging.exception('Bad thing happened: %s', e)
            """),
    ),
    fixer.SimplePythonFixer(
        message='logging.exception automatically records the message and full stack trace of the current exception, so it is redundant to pass the exception as the logging message. Instead, prefer to describe what action triggered the exception.',
        url='https://refex.readthedocs.io/en/latest/guide/fixers/logging_exceptions.html',
        significant=False,
        category=_LOGGING_EXCEPTION_CATEGORY,
        matcher=base_matchers.AllOf(
            base_matchers.Bind(
                'logging_exception',
                # `StmtPattern` does its own `Rebind` so we need to specify the
                # strategy for 'e' outside the inner `Bind`
                base_matchers.Rebind(
                    syntax_matchers.StmtPattern(
                        'logging.exception($arg)',
                        dict(
                            arg=ast_matchers.Name(
                                id=base_matchers.Bind('e',)))),
                    on_conflict=matcher_.BindConflict.MERGE_IDENTICAL),
            ),
            _in_exception_handler(
                'e', on_conflict=matcher_.BindConflict.MERGE_IDENTICAL),
            syntax_matchers.HasFirstAncestor(
                _Try(),
                _Try(
                    # For simplicity, try to match only cases where the try:
                    # block failure can clearly be caused only by the
                    # matched function call. This isn't perfect, since it
                    # will still match `foo(func_that_can_raise())` and it
                    # won't match cases where a try block has more than one
                    # statement but only one can obviously raise an error
                    # (for instance, a function call followed by continue,
                    # break, or return).
                    body=base_matchers.AllOf(
                        base_matchers.ItemsAre([
                            base_matchers.AllOf(
                                base_matchers.AnyOf(
                                    ast_matchers.Return(
                                        value=ast_matchers.Call(
                                            func=base_matchers.Bind('func'))),
                                    ast_matchers.Expr(
                                        value=ast_matchers.Call(
                                            func=base_matchers.Bind('func'))),
                                    ast_matchers.Assign(
                                        value=ast_matchers.Call(
                                            func=base_matchers.Bind('func'))),
                                ),
                                # TODO: Escape double quotes in the
                                # replacement
                                base_matchers.Unless(
                                    base_matchers.MatchesRegex(r'.+".+'))),
                        ]),),),
            )),
        replacement=dict(
            # TODO: Wrapping $func in quotes prevents the linter from
            # complaining if the outer quotes don't match the rest of the file,
            # since different quote style is allowed everywhere if it avoids
            # escaping. Is there a better option to keep the linter happy?
            # Also, in the case that all the arguments to $func were variables,
            # we might include them in the message (if they were function calls,
            # there's no guarantee the functions are pure).
            logging_exception=formatting.ShTemplate(
                "logging.exception('Call to \"$func\" resulted in an error')")),
        example_fragment=textwrap.dedent("""
          try:
            bar()
          except KeyError as e:
            logging.exception(e)
            """),
        example_replacement=textwrap.dedent("""
          try:
            bar()
          except KeyError as e:
            logging.exception('Call to "bar" resulted in an error')
            """),
    ),
)

SIMPLE_PYTHON_FIXERS = [
    # TODO: Uncomment this when it can pass through the test suite.
    # idiom_fixer('$a == None', '$a is None'),
    idiom_fixer('not $a is $b', '$a is not $b', category=_NEGATION_CATEGORY),
    idiom_fixer('not $a in $b', '$a not in $b', category=_NEGATION_CATEGORY),
    # The unnecessary comprehension fixers will suggest non-equivalent code if
    # someone writes [d['a'] for d['a'] in mything] but it's such an edge case
    # we don't even consider it.
    idiom_fixer(
        '[$a for $a in $b]',
        'list($b)',
        category=_UNNECESSARY_COMPREHENSION_CATEGORY),
    idiom_fixer(
        '{$a for $a in $b}',
        'set($b)',
        category=_UNNECESSARY_COMPREHENSION_CATEGORY),
] + list(_MUTABLE_CONSTANT_FIXERS) + list(_LOGGING_FIXERS)

# TODO(b/152805392): + _NONE_RETURNS_FIXERS
