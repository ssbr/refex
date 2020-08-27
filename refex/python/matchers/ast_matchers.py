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
# TODO: Add pytype support once pytype gets generics:
#  1) generate code in a genrule rather than generating classes at runtime.
#  2) Mark non-{expr,stmt} nodes specially since they won't have token spans.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import ast
import functools
import sys

import attr
import six

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
            field: matcher.submatcher_attrib(
                default=base_matchers.Anything(),
                kw_only=not six.PY2,
            ) for field in ast_node_type._fields
        },
        bases=(cls,),
        frozen=True,
    )
    # HACK: in Python 2 we can't use kw_only, so we simulate it by wrapping
    # __init__ with something taking no positional arguments. This only works
    # because _all_ parameters are kwonly.
    if six.PY2:
      # Note: functools.wraps() doesn't care if it's an unbound method object.
      old_init = ty.__init__

      @functools.wraps(old_init)
      def new_init(self, **kwargs):
        return old_init(self, **kwargs)

      ty.__init__ = new_init
    ty._ast_type = ast_node_type  # pylint: disable=protected-access
    return ty

  def _match(self, context, node):
    """Matches a node with the correct type and matching attributes."""
    if type(node) != self._ast_type:  # pylint: disable=unidiomatic-typecheck
      return None

    bindings = {}
    for field in self._ast_type._fields:
      submatcher = getattr(self, field)
      extra = submatcher.match(context, getattr(node, field, None))
      if extra is None:
        return None
      bindings = matcher.merge_bindings(bindings, extra.bindings)
      if bindings is None:
        return None
    return matcher.MatchInfo(
        matcher.create_match(context.parsed_file, node), bindings)


def _generate_syntax_matchers_for_type_tree(d, ast_node_type_root):
  matcher_type = _AstNodeMatcher._generate_syntax_matcher(ast_node_type_root)  # pylint: disable=protected-access
  d[matcher_type.__name__] = matcher.safe_to_eval(matcher_type)
  for subclass in ast_node_type_root.__subclasses__():
    _generate_syntax_matchers_for_type_tree(d, subclass)


_generate_syntax_matchers_for_type_tree(globals(), ast.AST)

# Compatibility classes. e.g. in 3.8, isinstance(ast.Num(3), ast.Num) is false.
# Instead, we replace with hand-written matchers that match an ast.Constant
# in the same circumstances. Same with any other backwards-incompatible changes.
if sys.version_info >= (3, 8):

  def _constant_match(context, candidate, value_matcher, value_types):
    if type(candidate) != ast.Constant:  # pylint: disable=unidiomatic-typecheck
      return None
    if not isinstance(candidate.value, value_types):
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

  @matcher.safe_to_eval
  @attr.s(frozen=True, kw_only=True)
  class Bytes(matcher.Matcher):
    s = matcher.submatcher_attrib(default=base_matchers.Anything())

    def _match(self, context, candidate):
      return _constant_match(context, candidate, self.s, bytes)

  @matcher.safe_to_eval
  @attr.s(frozen=True, kw_only=True)
  class Str(matcher.Matcher):
    s = matcher.submatcher_attrib(default=base_matchers.Anything())

    def _match(self, context, candidate):
      return _constant_match(context, candidate, self.s, str)

  @matcher.safe_to_eval
  @attr.s(frozen=True, kw_only=True)
  class NameConstant(matcher.Matcher):
    value = matcher.submatcher_attrib(default=base_matchers.Anything())

    def _match(self, context, candidate):
      return _constant_match(context, candidate, self.value, (bool, type(None)))

  # defined in _generate_syntax_matchers_for_type_tree, and shadows
  # the builtin Ellipsis.
  del Ellipsis  # pylint: disable=redefined-builtin
  # Store the Ellipsis builtin to avoid later shadowing by the Ellipsis matcher.
  _ELLIPSIS = Ellipsis  # pylint: disable=used-before-assignment

  @matcher.safe_to_eval  # pylint: disable=function-redefined
  @attr.s(frozen=True)
  class Ellipsis(matcher.Matcher):

    def _match(self, context, candidate):
      return _constant_match(context, candidate,
                             base_matchers.Equals(_ELLIPSIS), type(_ELLIPSIS))
