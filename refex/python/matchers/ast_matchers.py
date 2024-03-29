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
# pylint: disable=g-space-before-docstring-summary, g-no-space-after-docstring-summary, g-short-docstring-punctuation
# pyformat: disable
"""
:mod:`~refex.python.matchers.ast_matchers`
------------------------------------------

Automatically generated low-level AST node matchers.

For each AST node in the :py:mod:`ast` module, there is a matcher with the same
name, which accepts submatchers for each of its attributes.

For example, if the Python grammar has an entry like::

    UnaryOp(unaryop op, expr operand)

Then the following matcher will match any ``ast.UnaryOp``::

    ast_matchers.UnaryOp()

And this will match any ``ast.UnaryOp`` with an ``op`` attribute matching
``submatcher1``, and an ``operand`` attribute matching ``submatcher2``::

    ast_matchers.UnaryOp(op=submatcher1, operand=submatcher2)

(See the unit tests for more examples.)
"""
# pyformat: enable
# TODO: Add pytype support once pytype gets generics:
#  1) generate code in a genrule rather than generating classes at runtime.
#  2) Mark non-{expr,stmt} nodes specially since they won't have token spans.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import ast
import sys

import attr

from refex.python import matcher
from refex.python.matchers import base_matchers

_HAS_DYNAMIC_ATTRIBUTES = True


@attr.s(frozen=True)
class _AstNodeMatcher(matcher.Matcher):
  """Abstract / generic AST node matcher.

  Only use via the subclasses generated below. Subclasses will always have the
  name Ast<ast class name>. e.g. AstExpr.

  AST node matchers can be instantiated by providing matchers for the
  attributes. These all default to Any, so are not required.

  Missing fields are replaced with None in matching.
  """

  @classmethod
  def _generate_syntax_matcher(cls, ast_node_type):
    # Generate a class with an attrs field for every AST field, passed by
    # keyword argument only.
    ty = attr.make_class(
        ast_node_type.__name__,
        {
            field: matcher.submatcher_attrib(default=base_matchers.Anything(),)
            for field in ast_node_type._fields
        },
        bases=(cls,),
        frozen=True,
        kw_only=True,
    )
    ty._ast_type = ast_node_type  # pylint: disable=protected-access
    ty.type_filter = frozenset({ast_node_type})
    return ty

  @matcher.accumulating_matcher
  def _match(self, context, node):
    """Matches a node with the correct type and matching attributes."""
    if type(node) != self._ast_type:  # pylint: disable=unidiomatic-typecheck
      yield None

    for field in self._ast_type._fields:
      submatcher = getattr(self, field)
      yield submatcher.match(context, getattr(node, field, None))


def _generate_syntax_matchers_for_type_tree(d, ast_node_type_root):
  matcher_type = _AstNodeMatcher._generate_syntax_matcher(ast_node_type_root)  # pylint: disable=protected-access
  d[matcher_type.__name__] = matcher.safe_to_eval(matcher_type)
  for subclass in ast_node_type_root.__subclasses__():
    _generate_syntax_matchers_for_type_tree(d, subclass)


_generate_syntax_matchers_for_type_tree(globals(), ast.AST)

if sys.version_info < (3, 9):
  # Slices pre-3.9 don't carry a col_offset, causing them to, in some cases,
  # be completely incorrect.
  # In particular, they will be incorrect for slices with no subexpressions,
  # such as `foo[:]``, and for extended slices, such as `foo[:,i]`.
  # Rather than keep support around, we disable this, with a workaround
  # suggested for the very danger inclined.

  @matcher.safe_to_eval
  @attr.s(frozen=True, kw_only=True)
  class Subscript(Subscript):  # pylint: disable=undefined-variable
    slice = matcher.submatcher_attrib(default=base_matchers.Anything())

    @slice.validator
    def _slice_validator(self, attribute, value):
      del attribute  # unused
      if isinstance(value, base_matchers.Bind):
        raise ValueError(
            'slice=Bind(...) not supported in Python < 3.9. It will fail to '
            'correctly match e.g. `a[:]` or `a[1,:]`. Upgrade to Python 3.9, or'
            ' work around this using AllOf(Bind(...)) if that is OK.')


# Compatibility classes. e.g. in 3.8, isinstance(ast.Num(3), ast.Num) is false.
# Instead, we replace with hand-written matchers that match an ast.Constant
# in the same circumstances. Same with any other backwards-incompatible changes.
if sys.version_info >= (3, 8):

  def _constant_match(
      context,
      candidate,
      value_matcher: matcher.Matcher,
      value_types: tuple[type[object], ...],
  ):
    """Match an ``ast.Constant`` against a matcher and type."""
    if type(candidate) != ast.Constant:  # pylint: disable=unidiomatic-typecheck
      return None
    # note: not isinstance. The only concrete subclass that can occur in a
    # Constant AST is bool (which subclasses int). And in that case, we actually
    # don't want to include it -- Num() should not match `True`!.
    # Instead, all types must be listed out explicitly.
    if type(candidate.value) not in value_types:
      return None
    result = value_matcher.match(context, candidate.value)
    if result is None:
      return None
    return matcher.MatchInfo(
        matcher.create_match(context.parsed_file, candidate), result.bindings)

  @matcher.safe_to_eval
  @attr.s(frozen=True, kw_only=True)
  class Num(matcher.Matcher):
    n = matcher.submatcher_attrib(default=base_matchers.Anything())

    def _match(self, context, candidate):
      return _constant_match(context, candidate, self.n, (int, float, complex))

    type_filter = frozenset({ast.Constant})

  @matcher.safe_to_eval
  @attr.s(frozen=True, kw_only=True)
  class Bytes(matcher.Matcher):
    s = matcher.submatcher_attrib(default=base_matchers.Anything())

    def _match(self, context, candidate):
      return _constant_match(context, candidate, self.s, (bytes,))

    type_filter = frozenset({ast.Constant})

  @matcher.safe_to_eval
  @attr.s(frozen=True, kw_only=True)
  class Str(matcher.Matcher):
    s = matcher.submatcher_attrib(default=base_matchers.Anything())

    def _match(self, context, candidate):
      return _constant_match(context, candidate, self.s, (str,))

    type_filter = frozenset({ast.Constant})

  @matcher.safe_to_eval
  @attr.s(frozen=True, kw_only=True)
  class NameConstant(matcher.Matcher):
    value = matcher.submatcher_attrib(default=base_matchers.Anything())

    def _match(self, context, candidate):
      return _constant_match(context, candidate, self.value, (bool, type(None)))

    type_filter = frozenset({ast.Constant})

  @matcher.safe_to_eval
  @attr.s(frozen=True)
  class Ellipsis(matcher.Matcher):  # pylint: disable=redefined-builtin

    def _match(self, context, candidate):
      return _constant_match(context, candidate, base_matchers.Equals(...),
                             (type(...),))

    type_filter = frozenset({ast.Constant})
