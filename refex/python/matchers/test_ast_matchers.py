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
"""Tests for refex.python.matchers.ast_matchers."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import unittest

from absl.testing import absltest
from absl.testing import parameterized
import six

from refex import match
from refex.python import matcher
from refex.python.matchers import ast_matchers
from refex.python.matchers import base_matchers


def expression(e):
  parsed = matcher.parse_ast(e, '<string>')
  return parsed, parsed.tree.body[0].value


class RawAstTest(absltest.TestCase):

  def test_type_only(self):
    parsed, e = expression('~a')
    self.assertEqual(
        ast_matchers.UnaryOp().match(matcher.MatchContext(parsed), e),
        matcher.MatchInfo(
            matcher.LexicalASTMatch(e, parsed.text, e.first_token,
                                    e.last_token)))

  def test_explicit_anything(self):
    parsed, e = expression('~a')
    self.assertEqual(
        ast_matchers.UnaryOp(
            op=base_matchers.Anything(),
            operand=base_matchers.Anything()).match(
                matcher.MatchContext(parsed), e),
        matcher.MatchInfo(
            matcher.LexicalASTMatch(e, parsed.text, e.first_token,
                                    e.last_token)))

  def test_fully_specified_matcher(self):
    parsed, e = expression('~a')
    self.assertEqual(
        ast_matchers.UnaryOp(
            op=ast_matchers.Invert(),
            operand=ast_matchers.Name(ctx=ast_matchers.Load())).match(
                matcher.MatchContext(parsed), e),
        matcher.MatchInfo(
            matcher.LexicalASTMatch(e, parsed.text, e.first_token,
                                    e.last_token)))

  def test_type_mismatch(self):
    parsed, e = expression('a + b')
    self.assertIsNone(ast_matchers.UnaryOp().match(
        matcher.MatchContext(parsed), e))

  def test_submatcher_fail(self):
    parsed, e = expression('~a')
    self.assertIsNone(
        ast_matchers.UnaryOp(
            op=base_matchers.Unless(base_matchers.Anything())).match(
                matcher.MatchContext(parsed), e))

  def test_ancestor(self):
    """The matcher won't traverse into child nodes."""
    parsed = matcher.parse_ast('~a', '<string>')
    self.assertIsNone(
        ast_matchers.UnaryOp(
            op=base_matchers.Unless(base_matchers.Anything())).match(
                matcher.MatchContext(parsed), parsed.tree.body[0]))

  def test_non_lexical_node(self):
    """The matcher doesn't return lexical data for non-lexical AST nodes."""
    parsed, binop = expression('a + b')
    add = binop.op
    self.assertEqual(
        ast_matchers.Add().match(matcher.MatchContext(parsed), add),
        matcher.MatchInfo(match.ObjectMatch(add)))

  def test_positional_arguments(self):
    """Positional arguments are reserved for later use.

    Clang AST matchers use them as an implicit forAll, for example. This seems
    useful. But the default used by attrs is to define all the fields as
    positional arguments as well, and this is borderline useless -- nobody is
    going to remember what the order of the fields is. So it is forbidden, to
    ensure nobody relies on it. People might otherwise be tempted by e.g. Num,
    which has only one parameter. (Num(3) is readable, but still banned.)
    """
    with self.assertRaises(TypeError):
      ast_matchers.Num(3)  # n=3 is fine though.

    if not six.PY2:
      with self.assertRaises(TypeError):
        ast_matchers.Constant(3)  # value=3 is fine though.


class ConstantTest(parameterized.TestCase):
  """In Python 3.8, the AST hierarchy for constants was changed dramatically.

  To preserve compatibility with <3.8, we implement compatibility shims that
  reflect the old API. They're also potentially just plain handy.
  """

  @parameterized.parameters(
      ast_matchers.Num(n=0), ast_matchers.Num(n=0.0), ast_matchers.Num(n=0j),
      ast_matchers.Num())
  def test_num(self, num_matcher):
    for s in '0', '0.0', '0j':
      with self.subTest(s=s):
        parsed = matcher.parse_ast(s, '<string>')
        self.assertIsNotNone(
            num_matcher.match(
                matcher.MatchContext(parsed), parsed.tree.body[0].value))

  def test_num_non_number(self):
    parsed = matcher.parse_ast('"string"', '<string>')
    self.assertIsNone(ast_matchers.Num().match(
        matcher.MatchContext(parsed), parsed.tree.body[0].value))

  @unittest.skipIf(six.PY2, 'ast.Bytes is python 3 only')
  @parameterized.parameters(({'s': b''},), ({},))
  def test_bytes(self, kwargs):
    bytes_matcher = ast_matchers.Bytes(**kwargs)  # hack for py2
    parsed = matcher.parse_ast('b""', '<string>')
    self.assertIsNotNone(
        bytes_matcher.match(
            matcher.MatchContext(parsed), parsed.tree.body[0].value))

  @unittest.skipIf(six.PY2, 'ast.Bytes is python 3 only')
  def test_bytes_non_bytes(self):
    parsed = matcher.parse_ast('"string"', '<string>')
    self.assertIsNone(ast_matchers.Bytes().match(
        matcher.MatchContext(parsed), parsed.tree.body[0].value))

  @parameterized.parameters(ast_matchers.Str(s=''), ast_matchers.Str())
  def test_string(self, str_matcher):
    parsed = matcher.parse_ast('""', '<string>')
    self.assertIsNotNone(
        str_matcher.match(
            matcher.MatchContext(parsed), parsed.tree.body[0].value))

  def test_string_non_string(self):
    parsed = matcher.parse_ast('2', '<string>')
    self.assertIsNone(ast_matchers.Str().match(
        matcher.MatchContext(parsed), parsed.tree.body[0].value))

  def test_ellipsis(self):
    parsed = matcher.parse_ast('x[...]', '<string>')
    self.assertIsNotNone(ast_matchers.Ellipsis().match(
        matcher.MatchContext(parsed), parsed.tree.body[0].value.slice.value))

  def test_ellipsis_non_ellipsis(self):
    parsed = matcher.parse_ast('1', '<string>')
    self.assertIsNone(ast_matchers.Ellipsis().match(
        matcher.MatchContext(parsed), parsed.tree.body[0].value))

  @unittest.skipIf(six.PY2, 'NameConstant is python 3 only')
  @parameterized.parameters(True, False, None)
  def test_named_constant(self, constant):
    parsed = matcher.parse_ast(str(constant), '<string>')
    for m in ast_matchers.NameConstant(), ast_matchers.NameConstant(
        value=constant):
      with self.subTest(matcher=m):
        self.assertIsNotNone(
            m.match(matcher.MatchContext(parsed), parsed.tree.body[0].value))

  @unittest.skipIf(six.PY2, 'NameConstant is python 3 only')
  def test_named_constant_non_named_constant(self):
    parsed = matcher.parse_ast('1', '<string>')
    self.assertIsNone(ast_matchers.NameConstant().match(
        matcher.MatchContext(parsed), parsed.tree.body[0].value))


if __name__ == '__main__':
  absltest.main()
