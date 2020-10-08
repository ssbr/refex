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
:mod:`refex.substitution`
-------------------------

Substitutions with optional metadata. This forms the core data structure that
Refex traffics in: Refex finds :class:`Substitution` objects, displays them, and
actualizes the change they represent (if any).

.. autoclass:: Substitution
  :members:

Diffs
~~~~~

The following functions and classes can convert a Substitution into a diff.
(Actual formatting and display of the diff is left to callers, in particular
:mod:`refex.formatting`.)

.. autoclass:: LabeledSpan
   :members:

.. autoclass:: DiffSpan
   :members:

.. autofunction:: as_diff

.. autofunction:: labeled_spans

.. autofunction:: disjoint_substitutions

"""

from __future__ import absolute_import
from __future__ import division
# from __future__ import google_type_annotations
from __future__ import print_function

import collections
import operator
import re
from typing import (FrozenSet, Iterable, List, Mapping, Optional, Text, Tuple,
                    Union)

import attr
import six

# Only slightly structured category name: dot-separated, no empty intra-dot
# sequences, no whitespace, doesn't begin with a -, and doesn't begin/end on a
# dot.
_CATEGORY_NAME_REGEX = re.compile(r'\A[^-.\s][^.\s]*([.][^.\s]+)*\Z')


@attr.s(frozen=True)
class Substitution(object):
  """A search result containing optional replacements and metadata.

  The span of text being fixed is attached as a dict mapping span identifiers
  to (start, end) codepoint offsets (start is inclusive, end is not). The span
  identifiers are also used to identify replacements in the `replacement` dict.
  """

  #: Matched spans, keyed by label.
  matched_spans = attr.ib(type=Mapping[str, Tuple[int, int]])

  #: The label for the location of the :class:`Substitution`.
  primary_label = attr.ib(type=Text)

  #: A mapping from labels to replacement strings. If ``None``, then
  #: this is a match that may be a candidate for some substitution, but no
  #: replacements were specified.
  replacements = attr.ib(default=None, type=Optional[Mapping[str, Text]])

  #: A message describing the issue.
  message = attr.ib(default=None, type=Optional[Text])

  #: An URL describing the issue or fix in more detail.
  url = attr.ib(default=None, type=Optional[Text])

  #: If ``False``, this is more or less a trivial change, the
  #: description of which may be dropped if this substitution is combined with
  #: a significant substitution.
  significant = attr.ib(default=True, type=bool)

  #: A name to group fixes by. This can be used for separating out
  #: suggestions for statistics, suppressing categories of suggestions, etc.
  category = attr.ib(default=None, type=Optional[Text])

  #: A span by which to group the substitution, or ``None`` if it is ungrouped.
  #:
  #: The scope should ideally be as local as possible. For example, grouping by
  #: expression or by line is sensible.
  #:
  #: Suggestions with the same non-``None`` span may be merged.
  key_span = attr.ib(default=None, type=Optional[Tuple[int, int]])

  @property
  def primary_span(self) -> Tuple[int, int]:
    """A convenience attribute for the span for the primary label."""
    return self.matched_spans[self.primary_label]

  def __attrs_post_init__(self):
    self._validate()

  def _validate(self):
    """Validates the substitution object up-front.

    This is valuable because the substitutions are passed around and combined,
    so type errors might crop up far removed from where they are introduced.

    Raises:
      ValueError: the initialized Substitution was passed invalid arguments
        in __init__.
    """

    if (self.category is not None and
        _CATEGORY_NAME_REGEX.match(self.category) is None):
      raise ValueError(
          'Invalid category name: must be dot separated categories with'
          ' no leading dash. got: %r, want to match: %s' %
          (self.category, _CATEGORY_NAME_REGEX.pattern))
    if self.primary_label not in self.matched_spans:
      raise ValueError(
          'primary_label ({!r}) not in matched_spans ({!r})'.format(
              self.primary_label, self.matched_spans))
    if self.replacements is not None and not (six.viewkeys(self.replacements) <=
                                              six.viewkeys(self.matched_spans)):
      raise ValueError('replacements keys ({!r}) is not a subset of'
                       ' matched_spans keys ({!r})'.format(
                           sorted(self.matched_spans, key=repr),
                           sorted(self.replacements, key=repr)))

    if self.replacements is not None:
      for key, replacement in six.iteritems(self.replacements):
        if not isinstance(replacement, six.text_type):
          raise TypeError(
              'replacements[{key!r}] is of type {actual_type}, expected {expected_type}'
              .format(
                  key=key,
                  expected_type=six.text_type.__name__,
                  actual_type=type(replacement).__name__))

  def relative_to_span(self, start: int, end: int) -> "Substitution":
    """Returns a new substitution that is offset relative to the provided span.

    If ``sub`` is a :class:`Substitution` for ``s``, then
    ``sub.relative_to_span(a, b)`` is the equivalent substitution for
    ``s[a:b]``.

    Args:
      start: The start of the span to be relative to (inclusive).
      end: The end of the span to be relative to (exclusive).

    Returns:
      A new substitution in the substring, or else None if the substitution
      doesn't fit.
    """
    new_spans = {}
    for k, (old_start, old_end) in self.matched_spans.items():
      if start <= old_start and old_end <= end:
        new_spans[k] = old_start - start, old_end - start
      else:
        return None
    return attr.evolve(self, matched_spans=new_spans)

  def all_categories(self) -> Iterable[Optional[str]]:
    """Yields all categories the substitution is a member of.

    Categories form a hierarchy separated by a dot, so e.g. a substitution
    with category ``foo.bar.baz`` will be in categories ``foo`` and ``foo.bar``.

    Additionally, every substitution is in the root category, represented by the
    special value ``None``.
    """
    yield None
    if self.category is not None:
      split_category = self.category.split('.')
      for i, _ in enumerate(split_category):
        yield '.'.join(split_category[:i + 1])


def suppress_exclude_bytes(subs, exclude_ranges):
  """Filters out substitutions that intersect a byte range.

  Args:
    subs: An iterable of Substitution objects.
    exclude_ranges: A map of {category: [(start, end), ...], ...} A substitution
      is filtered out if it intersects a start-end pair for a category it is
      inside.

  Yields:
    Substitutions that don't intersect the excluded ranges.
  """
  for sub in subs:
    if not _sub_matches_ranges(sub, exclude_ranges):
      yield sub


def _sub_matches_ranges(sub, match_ranges):
  start, end = sub.primary_span
  for category in sub.all_categories():
    for match_start, match_end in match_ranges.get(category, []):
      if end > match_start and start < match_end:
        return True

  return False


@attr.s(frozen=True, order=False, eq=True)
class LabeledSpan(object):
  """A part of the original text, verbatim.

  A single LabeledSpan has exactly one set of labels that applied to it
  from the Substitution. When a new label begins, or an old label ends,
  a new Unchanged is created for the remaining span.
  """
  #: The start/end in the original string.
  span = attr.ib(type=Tuple[int, int])
  #: A frozenset of which labels matched this span.
  labels = attr.ib(type=FrozenSet[Text])


@attr.s(frozen=True, order=False, eq=True)
class DiffSpan(object):
  """A part of the diff that was changed by the Substitution.

  note that unlike :class:`LabeledSpan`, a label may begin or end in the
  middle of a Diff. However, labels are not allowed to have diffs
  that intersect, so ``label`` is the only label responsible for this
  diff.
  """
  #: The span in the original string.
  span = attr.ib(type=Tuple[int, int])
  #: The label responsible for this diff.
  label = attr.ib(type=Text)
  #: The text that the span is replaced with.
  after = attr.ib(type=Text)


def as_diff(sub: Substitution) -> Iterable[Union[LabeledSpan, DiffSpan]]:
  """Yields the diff represented by the substitution.

  Note that this is a diff-of-intent, and not necessarily a minimal
  diff. For example, replacing ``'foo'`` with ``'foo'`` will yield
  a ``Diff(before='foo', after='foo')``.

  The diff begins at the first line that the Substitution matches,
  and ends at the last line that the Substitution matches.

  Args:
    sub: The :class:`Substitution` to convert to a diff.

  Yields:

    :class:`DiffSpan`:
        A part of the line that the Substitution replaces.

    :class:`LabeledSpan`:
        A part of the diff that has no replacements, or which has a replacement
        that overlaps with a prior :class:`DiffSpan`.
  """
  # TODO: pretty sure we're supposed to ban those overlaps in
  # Substitution. They will produce a crash when you attempt to execute them.
  replacements = (sub.replacements or {}).keys()

  last_diff_end = 0

  for ls in labeled_spans(sub):
    if ls.span[0] < last_diff_end:
      # This LabeledSpan overlaps with a DiffSpan.
      # Since we get a new LabeledSpan whenever labels change, there is
      # guaranteed not to be a gap between the diff and the first LabeledSpan
      # after it, but we do need to skip ahead until we reach it.
      continue
    replacing_labels = {label for label in ls.labels if label in replacements}
    if not replacing_labels:
      yield ls
      continue

    # find a canonical "first" replacement to yield in the diff.
    # we do this by picking the largest one, breaking ties by
    # sorting by the label name.
    first_replacement_label = max(
        replacing_labels,
        key=lambda label: (sub.matched_spans[label][1], label))
    diff = DiffSpan(
        span=sub.matched_spans[first_replacement_label],
        label=first_replacement_label,
        after=sub.replacements[first_replacement_label],
    )
    last_diff_end = diff.span[1]
    yield diff


def labeled_spans(sub: Substitution):
  """Yields all :class:`LabeledSpan` objects for a :class:`Substitution`.

  Args:
    sub: The substitution in question.

  Returns:
    An iterator of every :class:`LabeledSpan` in the substitution, in sorted
    order.
  """
  start_to_labels = collections.defaultdict(set)
  end_to_labels = collections.defaultdict(set)
  for label, (start, end) in sub.matched_spans.items():
    start_to_labels[start].add(label)
    end_to_labels[end].add(label)

  starts = sorted(start_to_labels, reverse=True)
  ends = sorted(end_to_labels, reverse=True)
  current_labels = frozenset()
  range_start = None

  while starts or ends:
    pos = None
    to_add = set()
    to_remove = set()
    if starts and ends:
      start = starts[-1]
      end = ends[-1]
      if start <= end:
        # important to be <= -- if a label starts and ends immediately, we must
        # handle the start first.
        pos = start
        starts.pop()
        to_add |= start_to_labels[pos]
      else:
        pos = end
        ends.pop()
        to_remove |= end_to_labels[pos]
    elif starts:
      raise AssertionError(
          'Internal error: start of span came after it already ended: %s' % sub)
    elif ends:
      pos = ends.pop()
      to_remove |= end_to_labels[pos]
    if range_start is not None:
      yield LabeledSpan(span=(range_start, pos), labels=current_labels)
    range_start = pos
    current_labels = (current_labels | to_add) - to_remove


def disjoint_substitutions(subs: Iterable[Substitution]) -> List[Substitution]:
  """Returns ``subs`` without overlapping substitutions, in sorted order."""
  span_subs = [(sub.primary_span, sub) for sub in subs]
  span_subs.sort(key=operator.itemgetter(0))

  disjoint_subs = []

  # Loop over the substitutions, and only append each one after it's confirmed
  # that it doesn't intersect with the next, or is smaller than the next.
  # (So we don't add it until the next iteration of the loop, or after the
  # loop is over.)
  #
  # TODO: You know, reading it over again, isn't this totally wrong?
  # in particular, it decides based only on the very next substitution,
  # when it should e.g. keep going and try the one after that.
  # I should just use the exact algorithm at
  # https://en.wikipedia.org/wiki/Maximum_disjoint_set
  last_start = last_end = last_sub = None
  for (start, end), sub in span_subs:
    if last_sub is not None:
      if start >= last_end:
        # no collision!
        disjoint_subs.append(last_sub)
      else:
        # they collide, keep the smallest as a heuristic to keep as many as
        # we can.
        if end - start > last_end - last_start:
          continue

    last_start = start
    last_end = end
    last_sub = sub
  if last_sub is not None:
    disjoint_subs.append(last_sub)
  return disjoint_subs
