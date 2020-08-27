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
"""Tests for refex.python.matcher."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import ast
import collections
import textwrap

from absl.testing import absltest
from absl.testing import parameterized
import attr

from refex import match
from refex import parsed_file
from refex.python import matcher
from refex.python.matchers import ast_matchers
from refex.python.matchers import base_matchers

_FAKE_CONTEXT = matcher.MatchContext(matcher.parse_ast('', 'foo.py'))


@attr.s(frozen=True)
class _SubmatcherAttribsClass(object):
  submatcher = matcher.submatcher_attrib(default=base_matchers.Anything())
  submatcher_list = matcher.submatcher_list_attrib(
      default=(base_matchers.Anything(),))


class SubmatcherAttribTest(parameterized.TestCase):

  @parameterized.parameters(42, matcher.ImplicitEquals(42))
  def test_coerce(self, value):
    self.assertEqual(matcher.coerce(value), matcher.ImplicitEquals(42))

  def test_coerce_nounwrap(self):
    """One can test for equality against a matcher by explicitly matching."""
    meta_implicit_equals = matcher.ImplicitEquals(matcher.ImplicitEquals(42))
    self.assertEqual(matcher.coerce(meta_implicit_equals), meta_implicit_equals)

  @parameterized.parameters(42, matcher.ImplicitEquals(42))
  def test_submatcher_attrib(self, value):
    self.assertEqual(
        _SubmatcherAttribsClass(submatcher=value).submatcher,
        matcher.ImplicitEquals(42))

  def test_submatcher_list_attrib(self):
    self.assertEqual(
        _SubmatcherAttribsClass(
            submatcher_list=[42, matcher.ImplicitEquals(42)]).submatcher_list,
        [matcher.ImplicitEquals(42),
         matcher.ImplicitEquals(42)])


class MergeBindingsTest(absltest.TestCase):
  """Lower-level tests for merge_bindings."""

  def test_empty(self):
    self.assertEqual(matcher.merge_bindings({}, {}), {})

  def test_on_conflict_differs(self):
    with self.assertRaises(matcher.MatchError):
      matcher.merge_bindings(
          {'a': matcher.BoundValue(0, on_conflict=matcher.BindConflict.SKIP)},
          {'a': matcher.BoundValue(0, on_conflict=matcher.BindConflict.ERROR)},
      )

  def test_on_merge_differs(self):
    with self.assertRaises(matcher.MatchError):
      matcher.merge_bindings(
          {'a': matcher.BoundValue(0, on_merge=matcher.BindMerge.KEEP_FIRST)},
          {'a': matcher.BoundValue(0, on_merge=matcher.BindMerge.KEEP_LAST)},
      )

  def test_error(self):
    error_bindings = {'a': matcher.BoundValue(0, matcher.BindConflict.ERROR)}
    with self.assertRaises(matcher.MatchError):
      matcher.merge_bindings(error_bindings, error_bindings)

  def test_skip(self):
    skip_bindings = {'a': matcher.BoundValue(0, matcher.BindConflict.SKIP)}
    self.assertIsNone(matcher.merge_bindings(skip_bindings, skip_bindings))

  def test_noconflict(self):
    bindings = {'a': matcher.BoundValue(0)}
    self.assertEqual(matcher.merge_bindings({}, bindings), bindings)

  def test_error_after_skip(self):
    """ERROR should still raise even if it is processed after a skip."""
    # This is a gnarly thing to test, because dicts aren't ordered.
    # Even if we used OrderedDict, ordered dict key views don't (and can't)
    # preserve order when they're intersected and so on.

    @attr.s()
    class OrderedKeyView(object):
      """Ordered fake key view for deterministic key iteration order."""
      keys = attr.ib()

      def __sub__(self, other_ordered_key_view):
        if self.keys != other_ordered_key_view.keys:
          raise NotImplementedError(
              "Test ordered key view doesn't support this.")
        return frozenset()

      def __and__(self, other_ordered_key_view):
        # can't preserve order otherwise...
        if self.keys != other_ordered_key_view.keys:
          raise NotImplementedError("Can't preserve order.")
        return list(self.keys)

    @attr.s()
    class OrderedBindings(object):
      """OrderedDict wrapper that returns OrderedKeyView."""
      _dict = attr.ib(converter=collections.OrderedDict)

      def __getitem__(self, v):
        return self._dict[v]

      def keys(self):
        return OrderedKeyView(self._dict)

      viewkeys = keys

    bad_bindings = [
        ('a', matcher.BoundValue(0, matcher.BindConflict.SKIP)),
        ('b', matcher.BoundValue(0, matcher.BindConflict.ERROR)),
    ]

    for bindings in [bad_bindings, bad_bindings[::-1]]:
      with self.subTest(bindings=bindings):
        bindings = OrderedBindings(bindings)
        with self.assertRaises(matcher.MatchError):
          matcher.merge_bindings(bindings, bindings)


class AccumulatingMatcherTest(absltest.TestCase):

  def test_empty_matcher(self):

    class TestMatcher(matcher.Matcher):

      @matcher.accumulating_matcher
      def _match(self, context, candidate):
        return
        yield  # pylint: disable=unreachable

    self.assertIsNotNone(TestMatcher().match(_FAKE_CONTEXT, 0))

  def test_submatcher_extraction(self):
    """Tests that the return values of submatchers are sent to the generator."""

    class ValueReturningMatcher(matcher.Matcher):

      def _match(self, context, candidate):
        del candidate  # unused
        return matcher.MatchInfo(
            matcher.create_match(context.parsed_file, 'hello world'), {})

    class TestMatcher(matcher.Matcher):

      @matcher.accumulating_matcher
      def _match(self, context, candidate):
        results.append((yield ValueReturningMatcher().match(context,
                                                            candidate)))

    results = []
    TestMatcher().match(_FAKE_CONTEXT, 0)
    self.assertEqual(results, [match.StringMatch('hello world')])


class AstEquivalentTest(absltest.TestCase):

  def test_equivalent(self):
    stmt1, stmt2 = ast.parse('a\na').body
    self.assertTrue(matcher.ast_equivalent(stmt1, stmt2))

  def test_equivalent_nonast(self):
    self.assertTrue(matcher.ast_equivalent(1, 1))

  def test_nonequivalent(self):
    for lhs in [1, ast.parse('a').body[0]]:
      for rhs in [2, ast.parse('b').body[0]]:
        with self.subTest(lhs=lhs, rhs=rhs):
          self.assertFalse(matcher.ast_equivalent(lhs, rhs))

  def test_equivalent_diffcontext(self):
    assign = ast.parse('a = a').body[0]
    a_lvalue = assign.targets[0]
    a_rvalue = assign.value
    self.assertTrue(matcher.ast_equivalent(a_lvalue, a_rvalue))

  def test_equivalent_nan(self):
    """Identical objects are equivalent."""
    # TODO: Handle nan in a more principled way.
    nan = float('nan')
    self.assertTrue(matcher.ast_equivalent(nan, nan))


class CompareByIdTest(absltest.TestCase):
  """Tests for _CompareById since we're being slightly clever defining it."""

  def test_eq(self):
    obj = {}
    self.assertEqual(matcher._CompareById(obj), matcher._CompareById(obj))
    self.assertNotEqual(
        matcher._CompareById(obj), matcher._CompareById(obj.copy()))

  def test_hash(self):
    obj = {}
    objs = {matcher._CompareById(obj)}
    self.assertIn(matcher._CompareById(obj), objs)
    self.assertNotIn(matcher._CompareById(obj.copy()), objs)


class AstNavtest(parameterized.TestCase):

  def test_no_parent(self):
    parsed = matcher.parse_ast('1 + 2')
    self.assertIsNone(parsed.nav.get_parent(parsed.tree))

  def test_no_parent_notintree(self):
    parsed = matcher.parse_ast('1 + 2')
    self.assertIsNone(parsed.nav.get_parent(7))

  def test_no_parent_notintree_unhashable(self):
    """AST nodes are compared by identity for tree traversal."""
    parsed = matcher.parse_ast('1 + 2')
    self.assertIsNone(parsed.nav.get_parent([]))

  def test_parent(self):
    parsed = matcher.parse_ast('1 + 2')
    elts = parsed.tree.body
    self.assertIs(parsed.nav.get_parent(elts[0].value), elts[0])
    self.assertIs(parsed.nav.get_parent(elts[0]), elts)
    self.assertIs(parsed.nav.get_parent(elts), parsed.tree)

  def test_no_prev_sibling(self):
    parsed = matcher.parse_ast('1 + 2')
    elts = parsed.tree.body
    self.assertIsNone(parsed.nav.get_prev_sibling(elts[0]))

  def test_no_prev_sibling_notintree(self):
    parsed = matcher.parse_ast('1 + 2')
    self.assertIsNone(parsed.nav.get_prev_sibling(7))

  def test_prev_sibling(self):
    parsed = matcher.parse_ast('1 + 2; 3')
    elts = parsed.tree.body
    self.assertIs(parsed.nav.get_prev_sibling(elts[1]), elts[0])

  def test_prev_sibling_expr(self):
    parsed = matcher.parse_ast('[1, 2]')
    elts = parsed.tree.body[0].value.elts
    self.assertIs(parsed.nav.get_prev_sibling(elts[1]), elts[0])

  def test_no_next_sibling(self):
    parsed = matcher.parse_ast('1 + 2')
    elts = parsed.tree.body
    self.assertIsNone(parsed.nav.get_next_sibling(elts[0]))

  def test_no_next_sibling_notintree(self):
    parsed = matcher.parse_ast('1 + 2')

    self.assertIsNone(parsed.nav.get_next_sibling(7))

  def test_next_sibling(self):
    parsed = matcher.parse_ast('1 + 2; 3')
    elts = parsed.tree.body
    self.assertIs(parsed.nav.get_next_sibling(elts[0]), elts[1])

  def test_next_sibling_expr(self):
    parsed = matcher.parse_ast('[1, 2]')
    elts = parsed.tree.body[0].value.elts
    self.assertIs(parsed.nav.get_next_sibling(elts[0]), elts[1])

  def test_memoized_nodes(self):
    """Some nodes like the BinOp.op attribute are memoized, which we must undo.

    Otherwise, the parent would just be the last binop to be read, etc.
    """
    parsed = matcher.parse_ast('[1+2, 3+4, 5+6]')
    binop1, binop2, binop3 = parsed.tree.body[0].value.elts
    self.assertIs(parsed.nav.get_parent(binop1.op), binop1)
    self.assertIs(parsed.nav.get_parent(binop2.op), binop2)
    self.assertIs(parsed.nav.get_parent(binop3.op), binop3)

  def test_simple_node_exprstmt(self):
    parsed = matcher.parse_ast('[hello, world]')
    for child in ast.walk(parsed.tree.body[0]):
      with self.subTest(child=child):
        self.assertIs(parsed.nav.get_simple_node(child), parsed.tree.body[0])

  def test_simple_node_complexstmt(self):
    parsed = matcher.parse_ast('for x in y: pass')
    self.assertIsNone(parsed.nav.get_simple_node(parsed.tree.body[0]))

  def test_simple_node_is_expr(self):
    """In a non-simple statement, subexpressions are their own simple node."""
    parsed = matcher.parse_ast('for x in y: pass')
    for_stmt = parsed.tree.body[0]
    self.assertIs(parsed.nav.get_simple_node(for_stmt.target), for_stmt.target)
    self.assertIs(parsed.nav.get_simple_node(for_stmt.iter), for_stmt.iter)


class PragmaTest(parameterized.TestCase):

  def test_line_pragma(self):
    prefix = 'not_annotated()\n'
    suffix = 'a() # foo: bar=baz.quux'
    source = ''.join([prefix, suffix, '\nalso_not_annotated()'])
    self.assertEqual(
        matcher.parse_ast(source).pragmas, (parsed_file.Pragma(
            tag='foo',
            data={'bar': 'baz.quux'},
            start=len(prefix),
            end=len(prefix) + len(suffix)),))

  def test_module_scoped_pragma(self):
    source = '# foo: bar=baz.quux\nhello_world()'
    self.assertEqual(
        matcher.parse_ast(source).pragmas, (parsed_file.Pragma(
            tag='foo', data={'bar': 'baz.quux'}, start=0, end=len(source)),))

  @parameterized.parameters('  something\n', '')
  def test_locally_scoped_pragma(self, first_line):
    prefix = 'def foo():\n' + first_line
    suffix = '  # foo: bar=baz.quux\n  hello_world()\n\n'
    source = ''.join([prefix, suffix, 'def bar():\n  also_not_annotated()'])
    self.assertEqual(
        matcher.parse_ast(source).pragmas, (parsed_file.Pragma(
            tag='foo',
            data={'bar': 'baz.quux'},
            start=len(prefix),
            end=len(prefix) + len(suffix)),))

  def test_pragma_comment_only(self):
    source = '"foo: bar=baz.quux"'
    self.assertEqual(matcher.parse_ast(source).pragmas, ())

  def test_pragma_sorted(self):
    """Tests that pragmas are sorted.

    Scoped pragmas can't be resolved until after the end of the scope, so it is
    not clear that they would remain sorted with respect to line pragmas and
    other scoped pragmas. This test asserts that they are.
    """
    source = textwrap.dedent('''\
        # pragma: num=1
        pragma_2()  # pragma: num=2
        if True:
          # pragma: num=3
          pass
        ''')

    self.assertEqual(
        [pragma.data[u'num'] for pragma in matcher.parse_ast(source).pragmas],
        [u'1', u'2', u'3'])


class FindIterTest(absltest.TestCase):

  def test_matcherror(self):
    parsed = matcher.parse_ast('x+y')
    bind = base_matchers.Bind('var', on_conflict=matcher.BindConflict.ERROR)
    m = ast_matchers.BinOp(left=bind, right=bind)
    self.assertEqual(list(matcher.find_iter(m, parsed)), [])


class CreateMatchTest(absltest.TestCase):

  def testStringMatch(self):
    self.assertEqual(
        match.StringMatch('hello world'),
        matcher.create_match(_FAKE_CONTEXT.parsed_file, 'hello world'))

  def testObjectMatch(self):
    obj = object(),
    self.assertEqual(
        match.ObjectMatch(obj),
        matcher.create_match(_FAKE_CONTEXT.parsed_file, obj))


if __name__ == '__main__':
  absltest.main()
