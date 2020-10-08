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
"""Tests for refex.substitution."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from absl.testing import absltest
from absl.testing import parameterized

from refex import substitution


def _substitution_with_span(start, end, **kwargs):
  kwargs.setdefault('message', '')
  kwargs.setdefault('url', '')
  return substitution.Substitution(
      matched_spans={'label': (start, end)},
      primary_label='label',
      replacements={'label': u''},
      **kwargs)


class SubstitutionTest(parameterized.TestCase):

  def test_validate_primary_label(self):
    with self.assertRaises(ValueError):
      substitution.Substitution(
          message='',
          matched_spans={'label': (0, 0)},
          primary_label='label_dne',
          replacements={'label': u''},
          url='',
      )

  def test_validate_span_replacements(self):
    with self.assertRaises(ValueError):
      substitution.Substitution(
          message='',
          matched_spans={'label': (0, 0)},
          primary_label='label',
          replacements={'label_dne': u''},
          url='',
      )

  def test_validate_span_not_in_replacements(self):
    """It is OK to only replace a subset of matched spans."""
    # does not raise:
    substitution.Substitution(
        message='',
        matched_spans={'label': (0, 0)},
        primary_label='label',
        replacements={},
        url='',
    )

  def test_validate_replacement_not_in_spans(self):
    with self.assertRaises(ValueError):
      substitution.Substitution(
          message='',
          matched_spans={'label': (0, 0)},
          primary_label='label',
          replacements={
              'label': u'',
              'label2': u''
          },
          url='',
      )

  def test_validate_no_replacements(self):
    substitution.Substitution(
        primary_label='label',
        matched_spans={'label': (0, 0)},
        replacements=None,
    )

  @parameterized.parameters('.foo', 'foo.', '.foo.', 'foo ', 'foo bar',
                            'foo..bar', '-foo')
  def test_validate_category_failure(self, category):
    with self.assertRaises(ValueError):
      substitution.Substitution(
          primary_label='label',
          matched_spans={'label': (0, 0)},
          category=category,
      )

  @parameterized.parameters('foo', 'foo.bar', 'foo-', '_foo', 'foo.bar')
  def test_validate_category_success(self, category):
    substitution.Substitution(
        primary_label='label',
        matched_spans={'label': (0, 0)},
        category=category,
    )

  def test_relative_identical(self):
    self.assertEqual(
        _substitution_with_span(10, 20).relative_to_span(10, 20),
        _substitution_with_span(0, 10))

  def test_relative_subset(self):
    self.assertEqual(
        _substitution_with_span(10, 20).relative_to_span(5, 25),
        _substitution_with_span(5, 15))

  def test_out_of_bounds(self):
    for out_of_bounds_span in [(0, 10), (0, 15), (15, 30), (20, 30), (12, 18)]:
      with self.subTest(relative_to=out_of_bounds_span):
        self.assertIsNone(
            _substitution_with_span(10,
                                    20).relative_to_span(*out_of_bounds_span))

  def test_all_categories(self):
    self.assertEqual(
        list(
            _substitution_with_span(0, 1,
                                    category='foo.bar.baz').all_categories()),
        [None, 'foo', 'foo.bar', 'foo.bar.baz'])

  def test_all_categories_none(self):

    self.assertEqual(
        list(_substitution_with_span(0, 1, category=None).all_categories()),
        [None])


class SuppressTest(parameterized.TestCase):

  @parameterized.parameters((0, 1), (2, 3), (5, 6))
  def test_nointersect(self, start, end):
    sub = _substitution_with_span(start, end)
    self.assertEqual(
        list(substitution.suppress_exclude_bytes([sub], {None: [(1, 2)]})),
        [sub])

  @parameterized.parameters((0, 2), (1, 2), (2, 3), (5, 6), (5, 7), (0, 7))
  def test_intersect(self, start, end):
    sub = _substitution_with_span(start, end)
    self.assertEqual(
        list(substitution.suppress_exclude_bytes([sub], {None: [(1, 6)]})), [])

  @parameterized.parameters('foo.bar', 'foo.bar.baz')
  def test_category_match(self, category):
    sub = _substitution_with_span(0, 2, category=category)
    self.assertEqual(
        list(substitution.suppress_exclude_bytes([sub], {'foo.bar': [(0, 2)]})),
        [])

  @parameterized.parameters('foo', 'foo.not_bar', 'not_foo')
  def test_category_nomatch(self, category):
    sub = _substitution_with_span(0, 2, category=category)
    self.assertEqual(
        list(substitution.suppress_exclude_bytes([sub], {'foo.bar': [(0, 2)]})),
        [sub])


class LabeledSpanTest(absltest.TestCase):

  def test_empty_range(self):
    self.assertEqual(
        list(
            substitution.labeled_spans(
                substitution.Substitution(
                    matched_spans={'a': (0, 0)}, primary_label='a'))),
        [substitution.LabeledSpan(labels={'a'}, span=(0, 0))])

  def test_empty_range_next(self):
    self.assertEqual(
        list(
            substitution.labeled_spans(
                substitution.Substitution(
                    matched_spans={
                        'a': (0, 0),
                        'b': (1, 1)
                    }, primary_label='a'))), [
                        substitution.LabeledSpan(labels={'a'}, span=(0, 0)),
                        substitution.LabeledSpan(labels=set(), span=(0, 1)),
                        substitution.LabeledSpan(labels={'b'}, span=(1, 1))
                    ])

  def test_adjacent(self):
    self.assertEqual(
        list(
            substitution.labeled_spans(
                substitution.Substitution(
                    matched_spans={
                        'a': (0, 10),
                        'b': (10, 20)
                    },
                    primary_label='a'))),
        [
            substitution.LabeledSpan(labels={'a'}, span=(0, 10)),
            substitution.LabeledSpan(labels={'a', 'b'}, span=(10, 10)),
            substitution.LabeledSpan(labels={'b'}, span=(10, 20))
        ])

  def test_gap(self):
    self.assertEqual(
        list(
            substitution.labeled_spans(
                substitution.Substitution(
                    matched_spans={
                        'a': (0, 10),
                        'b': (20, 30)
                    },
                    primary_label='a'))), [
                        substitution.LabeledSpan(labels={'a'}, span=(0, 10)),
                        substitution.LabeledSpan(labels=set(), span=(10, 20)),
                        substitution.LabeledSpan(labels={'b'}, span=(20, 30))
                    ])

  def test_overlap(self):
    self.assertEqual(
        list(
            substitution.labeled_spans(
                substitution.Substitution(
                    matched_spans={
                        'a': (0, 10),
                        'b': (5, 15)
                    },
                    primary_label='a'))),
        [
            substitution.LabeledSpan(labels={'a'}, span=(0, 5)),
            substitution.LabeledSpan(labels={'a', 'b'}, span=(5, 10)),
            substitution.LabeledSpan(labels={'b'}, span=(10, 15))
        ])

  def test_total_overlap(self):
    self.assertEqual(
        list(
            substitution.labeled_spans(
                substitution.Substitution(
                    matched_spans={
                        'a': (0, 10),
                        'b': (0, 10)
                    },
                    primary_label='a'))),
        [substitution.LabeledSpan(labels={'a', 'b'}, span=(0, 10))])

  def test_total_overlap_start(self):
    self.assertEqual(
        list(
            substitution.labeled_spans(
                substitution.Substitution(
                    matched_spans={
                        'a': (0, 10),
                        'b': (0, 15)
                    },
                    primary_label='a'))),
        [
            substitution.LabeledSpan(labels={'a', 'b'}, span=(0, 10)),
            substitution.LabeledSpan(labels={'b'}, span=(10, 15))
        ])

  def test_total_overlap_end(self):
    self.assertEqual(
        list(
            substitution.labeled_spans(
                substitution.Substitution(
                    matched_spans={
                        'a': (0, 10),
                        'b': (5, 10)
                    },
                    primary_label='a'))),
        [
            substitution.LabeledSpan(labels={'a'}, span=(0, 5)),
            substitution.LabeledSpan(labels={'a', 'b'}, span=(5, 10))
        ])

  def test_swapped_order_empty(self):
    """Test what 'shouldn't happen'."""
    with self.assertRaises(AssertionError):
      list(
          substitution.labeled_spans(
              substitution.Substitution(
                  matched_spans={'a': (10, 5)}, primary_label='a')))


if __name__ == '__main__':
  absltest.main()
