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

# python3 python2
"""Tests for refex.python.matchers.base_matchers."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import ast

from absl.testing import absltest
from absl.testing import parameterized
from unittest import mock
from refex import match
from refex.python import evaluate
from refex.python import matcher
from refex.python import matcher_test_util
from refex.python.matchers import ast_matchers
from refex.python.matchers import base_matchers
from six.moves import range

_NOTHING = base_matchers.Unless(base_matchers.Anything())
_FAKE_CONTEXT = matcher.MatchContext(matcher.parse_ast('', 'foo.py'))


class BindTest(absltest.TestCase):

  def test_bind_name_invalid(self):
    with self.assertRaises(ValueError):
      base_matchers.Bind('__foo')

  def test_systembind_name_valid(self):
    base_matchers.SystemBind('__foo')

  def test_systembind_name_invalid(self):
    with self.assertRaises(ValueError):
      base_matchers.SystemBind('foo')

  def test_systembind_not_user_visible(self):
    with self.assertRaises(ValueError):
      evaluate.compile_matcher('SystemBind("__foo")')

  def test_bind(self):
    self.assertEqual(
        base_matchers.Bind('foo').match(_FAKE_CONTEXT, 1),
        matcher.MatchInfo(
            match.ObjectMatch(1),
            {'foo': matcher.BoundValue(match.ObjectMatch(1))}))

  def test_bind_2arg(self):
    self.assertEqual(
        base_matchers.Bind('foo',
                           base_matchers.Anything()).match(_FAKE_CONTEXT, 1),
        matcher.MatchInfo(
            match.ObjectMatch(1),
            {'foo': matcher.BoundValue(match.ObjectMatch(1))}))

  def test_bind_miss(self):
    self.assertIsNone(
        base_matchers.Bind('foo', _NOTHING).match(_FAKE_CONTEXT, 1))

  # The rest of the tests are for an explicit on_conflict / on_merge.

  def match_conflict(self, v1, v2, on_conflict=None, on_merge=None):
    """Matches v1 and v2 with conflicting Binds with the provided on_conflict.

    Args:
      v1: value for the first Bind() to match.
      v2: value for the second Bind() to match.
      on_conflict: a BindConflict enum value or None.
      on_merge: a BindMerge enum value or None.

    Returns:
      If the match failed, returns None. Otherwise, returns the BoundValue.value
      for the conflicting bind.
    """
    expr = evaluate.compile_matcher("""AllOf(
            HasItem(0, Bind("x", on_conflict={on_conflict}, on_merge={on_merge})),
            HasItem(1, Bind("x", on_conflict={on_conflict}, on_merge={on_merge})),
    )""".format(on_conflict=on_conflict, on_merge=on_merge))

    value = [v1, v2]

    result = expr.match(_FAKE_CONTEXT, value)
    if result is None:
      return None
    return result.bindings['x'].value.matched

  def test_noconflict(self):
    for on_conflict in matcher.BindConflict:
      with self.subTest(on_conflict=on_conflict):
        bind = base_matchers.Bind('x', on_conflict=on_conflict)
        result = bind.match(_FAKE_CONTEXT, 42)
        self.assertIsNotNone(result)
        self.assertEqual(result.bindings['x'].value.matched, 42)

  def test_skip(self):
    self.assertIsNone(self.match_conflict(42, 42, matcher.BindConflict.SKIP))

  def test_error(self):
    with self.assertRaises(matcher.MatchError):
      self.match_conflict(42, 42, matcher.BindConflict.ERROR)

  def test_keep_first(self):
    self.assertEqual(
        self.match_conflict(0, 42, on_merge=matcher.BindMerge.KEEP_FIRST), 0)

  def test_keep_last(self):
    self.assertEqual(
        self.match_conflict(0, 42, on_merge=matcher.BindMerge.KEEP_LAST), 42)

  def test_merge_ideq_success(self):
    for on_conflict in [
        matcher.BindConflict.MERGE_IDENTICAL,
        matcher.BindConflict.MERGE_IDENTICAL_OR_ERROR,
        matcher.BindConflict.MERGE_EQUIVALENT_AST,
        matcher.BindConflict.MERGE_EQUIVALENT_AST_OR_ERROR,
    ]:
      with self.subTest(on_conflict=on_conflict):
        self.assertEqual(self.match_conflict(42, 42, on_conflict), 42)

  def test_merge_ideq_failure(self):
    for on_conflict in [
        matcher.BindConflict.MERGE_IDENTICAL,
        matcher.BindConflict.MERGE_EQUIVALENT_AST,
    ]:
      with self.subTest(on_conflict=on_conflict):
        self.assertIsNone(self.match_conflict(0, 42, on_conflict))

  def test_merge_ideq_or_error_failure(self):
    for on_conflict in [
        matcher.BindConflict.MERGE_IDENTICAL_OR_ERROR,
        matcher.BindConflict.MERGE_EQUIVALENT_AST_OR_ERROR,
    ]:
      with self.subTest(on_conflict=on_conflict):
        with self.assertRaises(matcher.MatchError):
          self.assertIsNone(self.match_conflict(0, 42, on_conflict))

  def test_merge_equivalent_but_not_identical(self):
    """An AST doesn't count as identical unless it is _literally_ the same ast.

    If this were not so, we'd run into trouble from matching different ASTs in
    different parts of the tree, which may actually produce different behavior
    when changed or if you navigate through them (e.g. go to the parent).
    """
    a1, a2 = ast.parse('a\na').body
    self.assertIsNone(
        self.match_conflict(a1, a2, matcher.BindConflict.MERGE_IDENTICAL))
    for a in [a1, a2]:
      self.assertEqual(
          self.match_conflict(a, a, matcher.BindConflict.MERGE_IDENTICAL), a)

  def test_asts_merge_equivalent_nonidentical(self):
    stmts = ast.parse('a\na').body
    for stmt1 in stmts:
      for stmt2 in stmts:
        with self.subTest(stmt1=stmt1, stmt2=stmt2):
          self.assertEqual(
              self.match_conflict(stmt1, stmt2,
                                  matcher.BindConflict.MERGE_EQUIVALENT_AST),
              stmt2)

  def test_asts_merge_equivalent_ctx(self):
    assign = ast.parse('a = a').body[0]
    a_lvalue = assign.targets[0]
    a_rvalue = assign.value
    self.assertEqual(
        self.match_conflict(a_lvalue, a_rvalue,
                            matcher.BindConflict.MERGE_EQUIVALENT_AST),
        a_rvalue)


class RebindTest(absltest.TestCase):

  def test_rebind_to_skip(self):
    m = evaluate.compile_matcher("""AllOf(
            HasItem(0, Rebind(Bind("x"), on_conflict=BindConflict.SKIP)),
            HasItem(1, Rebind(Bind("x"), on_conflict=BindConflict.SKIP)),
    )""")

    self.assertIsNone(m.match(_FAKE_CONTEXT, [1, 1]))

  def test_rebind_to_unskip(self):
    m = evaluate.compile_matcher("""AllOf(
            HasItem(0, Rebind(Bind("x", on_conflict=BindConflict.SKIP),
                              on_conflict=BindConflict.MERGE)),
            HasItem(1, Rebind(Bind("x", on_conflict=BindConflict.SKIP),
                              on_conflict=BindConflict.MERGE)),
    )""")

    result = m.match(_FAKE_CONTEXT, [1, 1])
    self.assertIsNotNone(result)
    self.assertEqual(result.bindings['x'].value.matched, 1)


class ContainsTest(absltest.TestCase):

  def test_contains(self):
    items = ['item1', 'item2', 'item3']
    m = base_matchers.Contains('item2')
    expected = matcher.MatchInfo(match.ObjectMatch(items))
    self.assertEqual(m.match(_FAKE_CONTEXT, items), expected)

  def test_contains_miss(self):
    items = ['item1', 'item2', 'item3']
    m = base_matchers.Contains('notthere')
    self.assertIsNone(m.match(_FAKE_CONTEXT, items))

  def test_contains_binds(self):
    items = [1, 2, 3]
    m = base_matchers.Contains(base_matchers.Bind('foo', 1))
    expected = matcher.MatchInfo(
        match.ObjectMatch(items),
        {'foo': matcher.BoundValue(match.ObjectMatch(1))})
    self.assertEqual(m.match(_FAKE_CONTEXT, items), expected)

  def test_contains_wrongtype(self):
    """It's useful to run a Contains() check against arbitrary objects."""
    m = base_matchers.Contains(base_matchers.Anything())
    self.assertIsNone(m.match(_FAKE_CONTEXT, object()))


class AnythingTest(absltest.TestCase):

  def test_anything(self):
    self.assertEqual(base_matchers.Anything().match(_FAKE_CONTEXT, 1),
                     matcher.MatchInfo(match.ObjectMatch(1)))


class AllOfTest(absltest.TestCase):

  def test_empty(self):
    self.assertEqual(base_matchers.AllOf().match(_FAKE_CONTEXT, 1),
                     matcher.MatchInfo(match.ObjectMatch(1)))

  def test_multi_bind(self):
    self.assertEqual(
        base_matchers.AllOf(
            base_matchers.Bind('foo'),
            base_matchers.Bind('bar')).match(_FAKE_CONTEXT, 1),
        matcher.MatchInfo(
            match.ObjectMatch(1), {
                'foo': matcher.BoundValue(match.ObjectMatch(1)),
                'bar': matcher.BoundValue(match.ObjectMatch(1)),
            }))

  def test_multi_fail(self):
    self.assertIsNone(
        base_matchers.AllOf(
            base_matchers.Bind('foo'),
            base_matchers.Bind('bar', _NOTHING)).match(_FAKE_CONTEXT, 1))

  def test_multi_overlap(self):
    # TODO: it'd be nice to give a good error at some point, instead.
    self.assertEqual(
        base_matchers.AllOf(
            base_matchers.Bind('foo'),
            base_matchers.Bind('foo')).match(_FAKE_CONTEXT, 1),
        matcher.MatchInfo(
            match.ObjectMatch(1),
            {'foo': matcher.BoundValue(match.ObjectMatch(1))}))


class AnyOfTest(absltest.TestCase):

  def test_empty(self):
    self.assertEqual(base_matchers.AllOf().match(_FAKE_CONTEXT, 1),
                     matcher.MatchInfo(match.ObjectMatch(1)))

  def test_multi_bind(self):
    self.assertEqual(
        base_matchers.AnyOf(
            base_matchers.Bind('foo'),
            base_matchers.Bind('bar')).match(_FAKE_CONTEXT, 1),
        matcher.MatchInfo(
            match.ObjectMatch(1),
            {'foo': matcher.BoundValue(match.ObjectMatch(1))}))

  def test_multi_bind_second(self):
    self.assertEqual(
        base_matchers.AnyOf(
            base_matchers.Bind('foo', _NOTHING),
            base_matchers.Bind('bar')).match(_FAKE_CONTEXT, 1),
        matcher.MatchInfo(
            match.ObjectMatch(1),
            {'bar': matcher.BoundValue(match.ObjectMatch(1))}))

  def test_multi_bind_first(self):
    self.assertEqual(
        base_matchers.AnyOf(
            base_matchers.Bind('foo'), base_matchers.Bind('bar'),
            _NOTHING).match(_FAKE_CONTEXT, 1),
        matcher.MatchInfo(
            match.ObjectMatch(1),
            {'foo': matcher.BoundValue(match.ObjectMatch(1))}))

  def test_multi_bind_fail(self):
    self.assertIsNone(
        base_matchers.AllOf(
            base_matchers.Bind('foo', _NOTHING),
            base_matchers.Bind('bar', _NOTHING)).match(_FAKE_CONTEXT, 1))


class UnlessTest(absltest.TestCase):

  def test_unless(self):
    self.assertIsNone(
        base_matchers.Unless(base_matchers.Bind('foo')).match(_FAKE_CONTEXT, 1))

  def test_double_unless_erasure(self):
    self.assertEqual(
        base_matchers.Unless(base_matchers.Unless(
            base_matchers.Bind('foo'))).match(_FAKE_CONTEXT, 1),
        matcher.MatchInfo(match.ObjectMatch(1)))

  def test_unless_bindings(self):
    unless_bind = base_matchers.Unless(
        base_matchers.Bind('name', base_matchers.Anything()))
    self.assertEqual(unless_bind.bind_variables, set())


class EqualsTest(parameterized.TestCase):

  @parameterized.parameters(
      3,
      matcher.ImplicitEquals(3),
      base_matchers.Equals(3),
  )
  def test_eq(self, m):
    self.assertEqual(
        base_matchers.Bind('a', m).match(_FAKE_CONTEXT, 3),
        matcher.MatchInfo(
            match.ObjectMatch(3),
            {'a': matcher.BoundValue(match.ObjectMatch(3))}))

  @parameterized.parameters(
      3,
      matcher.ImplicitEquals(3),
      base_matchers.Equals(3),
  )
  def test_ne(self, m):
    self.assertIsNone(base_matchers.Bind('a', m).match(_FAKE_CONTEXT, 4))

  def test_nan(self):
    # Just for fun.
    nan = float('nan')
    self.assertIsNone(base_matchers.Equals(nan).match(_FAKE_CONTEXT, nan))


class MatchesRegexTest(absltest.TestCase):

  def test_matches(self):
    parsed = matcher.parse_ast('xy = 2', '<string>')
    matches = list(
        matcher.find_iter(
            base_matchers.MatchesRegex(r'^(?P<name>.)(.)$',
                                       base_matchers.Bind('inner')), parsed))
    # There is only one AST node of length >= 2 (which the regex requires): xy.
    self.assertEqual(matches, [
        matcher.MatchInfo(
            mock.ANY, {
                'inner': mock.ANY,
                'name': matcher.BoundValue(match.SpanMatch('x', (0, 1))),
            })
    ])
    [matchinfo] = matches
    self.assertEqual(matchinfo.match.span, (0, 2))
    self.assertEqual(matchinfo.match, matchinfo.bindings['inner'].value)

  def test_fullmatch_semantics(self):
    """The regexp only matches the full expression."""
    for var in ['x_', '_x']:
      with self.subTest(var=var):
        parsed = matcher.parse_ast(var, '<string>')
        self.assertEqual(
            list(matcher.find_iter(base_matchers.MatchesRegex(r'x'), parsed)),
            [])

  def test_nomatches(self):
    parsed = matcher.parse_ast('xy = 2', '<string>')
    matches = list(
        matcher.find_iter(base_matchers.MatchesRegex(r'not found'), parsed))
    self.assertEqual(matches, [])

  def test_inner_nomatches(self):
    parsed = matcher.parse_ast('xy = 2', '<string>')
    matches = list(
        matcher.find_iter(
            base_matchers.MatchesRegex(
                r'', base_matchers.Unless(base_matchers.Anything())), parsed))
    self.assertEqual(matches, [])

  def test_bind_variables(self):
    self.assertEqual(
        base_matchers.MatchesRegex('(?P<name>x)(y)').bind_variables, {'name'})

  def test_bindings(self):
    parsed = matcher.parse_ast('2', '<string>')
    matches = list(
        matcher.find_iter(
            base_matchers.MatchesRegex(r'(?P<var>.)', ast_matchers.Num()),
            parsed))
    self.assertLen(matches, 1)
    [m] = matches
    self.assertIn('var', m.bindings)
    self.assertEqual(m.bindings['var'].value.span, (0, 1))


class FileMatchesRegexTest(absltest.TestCase):

  def test_matches(self):
    parsed = matcher.parse_ast('var_hello = 42', '<string>')
    m = base_matchers.AllOf(
        base_matchers.FileMatchesRegex('hello'), ast_matchers.Num())

    matches = list(matcher.find_iter(m, parsed))

    self.assertLen(matches, 1)

  def test_doesnt_match(self):
    parsed = matcher.parse_ast('hi = 42', '<string>')
    m = base_matchers.AllOf(
        base_matchers.FileMatchesRegex('hello'), ast_matchers.Num())

    matches = list(matcher.find_iter(m, parsed))

    self.assertEqual(matches, [])

  def test_multi_regex(self):
    """Tests that the lazy dictionary doesn't walk over itself or something."""
    parsed = matcher.parse_ast('var_hello = 42', '<string>')
    m = base_matchers.AllOf(
        base_matchers.FileMatchesRegex('var'),
        base_matchers.FileMatchesRegex('hello'),
        base_matchers.FileMatchesRegex('42'),
        base_matchers.FileMatchesRegex(r'\Avar_hello = 42\Z'),
        ast_matchers.Num())

    matches = list(matcher.find_iter(m, parsed))

    self.assertLen(matches, 1)

  def test_bind_variables(self):
    self.assertEqual(
        base_matchers.FileMatchesRegex('(?P<name>x)(y)').bind_variables,
        {'name'})

  def test_bindings(self):
    parsed = matcher.parse_ast('x = 2', '<string>')
    matches = list(
        matcher.find_iter(
            base_matchers.AllOf(
                base_matchers.FileMatchesRegex(r'(?P<var>x)'),
                ast_matchers.Num()), parsed))
    self.assertLen(matches, 1)
    [m] = matches
    self.assertIn('var', m.bindings)
    self.assertEqual(m.bindings['var'].value.span, (0, 1))


class HasItemTest(absltest.TestCase):

  def test_has_no_item(self):
    for empty_container in ((), [], {}, ''):
      with self.subTest(empty_container=empty_container):
        self.assertIsNone(
            base_matchers.HasItem(0).match(_FAKE_CONTEXT, empty_container))

  def test_string(self):
    self.assertEqual(
        base_matchers.HasItem(1, base_matchers.Bind('a')).match(
            _FAKE_CONTEXT, 'xy'),
        matcher.MatchInfo(
            match.StringMatch('xy'),
            {'a': matcher.BoundValue(match.StringMatch('y'))}))

  def test_simple(self):
    for nonempty_container in (('x', 'y'), ['x', 'y'], {1: 'y'}):
      with self.subTest(nonempty_container=nonempty_container):
        self.assertEqual(
            base_matchers.HasItem(1, base_matchers.Bind('a')).match(
                _FAKE_CONTEXT, nonempty_container),
            matcher.MatchInfo(
                match.ObjectMatch(nonempty_container),
                {'a': matcher.BoundValue(match.StringMatch('y'))}))

  def test_negative_index(self):
    container = ['xyz']
    self.assertEqual(
        base_matchers.HasItem(-1, base_matchers.Bind('a')).match(
            _FAKE_CONTEXT, container),
        matcher.MatchInfo(
            match.ObjectMatch(container),
            {'a': matcher.BoundValue(match.StringMatch('xyz'))}))

  def test_submatch_rejects(self):
    self.assertIsNone(
        base_matchers.HasItem(-1, base_matchers.Unless(
            base_matchers.Anything())).match(_FAKE_CONTEXT, ['xyz']))

  def test_wrongtype(self):
    m = base_matchers.HasItem(0, base_matchers.Anything())
    self.assertIsNone(m.match(_FAKE_CONTEXT, object()))


class ItemsAreTest(absltest.TestCase):

  def test_too_short(self):
    self.assertIsNone(
        base_matchers.ItemsAre([base_matchers.Anything()
                               ]).match(_FAKE_CONTEXT, []))

  def test_too_long(self):
    self.assertIsNone(base_matchers.ItemsAre([]).match(_FAKE_CONTEXT, [1]))

  def test_submatcher_wrong(self):
    self.assertIsNone(
        base_matchers.ItemsAre([base_matchers.Unless(base_matchers.Anything())
                               ]).match(_FAKE_CONTEXT, [1]))

  def test_match(self):
    container = [1]
    self.assertEqual(
        base_matchers.ItemsAre([base_matchers.Bind('a')
                               ]).match(_FAKE_CONTEXT, container),
        matcher.MatchInfo(
            match.ObjectMatch(container),
            {'a': matcher.BoundValue(match.ObjectMatch(1))}))


class RecursivelyWrappedTest(
    matcher_test_util.MatcherTestCase, parameterized.TestCase):

  @parameterized.parameters([
      ('5', ['5']),
      ('~5', ['~5']),
      ('~~5', ['~~5']),
      ('~~5, ~3, 2', ['~~5', '~3', '2']),
      ('foo(~~5, ~3, 2)', ['~~5', '~3', '2']),
  ])
  def test_nested_invert(self, source, matches):
    self.assertEqual(
        self.get_all_match_strings(
            base_matchers.RecursivelyWrapped(
                ast_matchers.Num(), lambda i: ast_matchers.UnaryOp(
                    op=ast_matchers.Invert(), operand=i)), source), matches)

  def test_repr(self):
    # It turns out attrs automatically handles cyclic objects, but we can
    # improve on its repr.
    self.assertEqual(
        repr(
            base_matchers.RecursivelyWrapped(
                ast_matchers.Num(), lambda i: ast_matchers.UnaryOp(
                    op=ast_matchers.Invert(), operand=i))),
        'RecursivelyWrapped(_matchers=(Num(n=Anything()),'
        ' UnaryOp(op=Invert(), operand=_Recurse(...))))')

  def test_recursive_bindings(self):
    """Recursive matchers cover both recursive/base cases in .bind_variables.

    If this test fails with a RecursionError, that is a problem.
    """
    m = base_matchers.RecursivelyWrapped(
        base_matchers.Bind('base_case', ast_matchers.Num()),
        lambda i: base_matchers.Bind(
            'recursive_case',
            ast_matchers.UnaryOp(op=ast_matchers.Invert(), operand=i)))
    self.assertEqual(m.bind_variables, {'base_case', 'recursive_case'})

  def test_eq(self):
    """Different RecursivelyWrapped nodes with the same structure are equal."""
    x, y = [
        base_matchers.RecursivelyWrapped(
            ast_matchers.Num(),
            lambda i: ast_matchers.UnaryOp(op=ast_matchers.Invert(), operand=i))
        for _ in range(2)
    ]
    self.assertEqual(x, y)

  def test_ne(self):
    base = ast_matchers.Num()
    recursive = lambda m: ast_matchers.UnaryOp(
        op=ast_matchers.Invert(), operand=m)
    example_matcher = base_matchers.RecursivelyWrapped(base, recursive)

    different_1 = base_matchers.RecursivelyWrapped(
        base_matchers.Unless(base), recursive)
    different_2 = base_matchers.RecursivelyWrapped(
        base, lambda m: base_matchers.Unless(recursive(m)))

    for different_matcher in [different_1, different_2]:
      self.assertNotEqual(example_matcher, different_matcher)


class MaybeWrappedTest(
    matcher_test_util.MatcherTestCase, parameterized.TestCase):

  @parameterized.parameters([
      ('5', ['5']),
      ('~5', ['~5']),
      ('~~5', ['~5']),
      ('~~5, ~3, 2', ['~5', '~3', '2']),
      ('foo(~~5, ~3, 2)', ['~5', '~3', '2']),
  ])
  def test_nested_invert(self, source, matches):
    self.assertEqual(
        self.get_all_match_strings(
            base_matchers.MaybeWrapped(
                ast_matchers.Num(), lambda i: ast_matchers.UnaryOp(
                    op=ast_matchers.Invert(), operand=i)), source), matches)


class InLineTest(matcher_test_util.MatcherTestCase):

  def test_match_lines(self):
    source = 'a = b\nc = d\ne = f\ng = h'
    self.assertEqual(
        self.get_all_match_strings(
            base_matchers.InLines(lines=[2, 4]), source), ['c = d', 'g = h'])


if __name__ == '__main__':
  absltest.main()
