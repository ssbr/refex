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
:mod:`refex.match`
==================

The common match classes, used for representing fragments for substitution.

This is the bare minimum of match information, common to all search modes.
:mod:`refex.python.matcher` has matchers that carry information about the AST,
which can be used for more sophisticated search/replace functionality.

All match classes have the following two attributes:

.. attribute:: string
   :type: Optional[str]

   If this is non-``None``, this is the value that was matched as a string.
   This value is used when the match is used as a *source* for a substitution.

.. attribute:: span
   :type: Optional[Tuple[int, int]]

   If this is non-None, then this is the location of the match in the source
   file. This value is used when the match is used as a _destination_ for
   a substitution.

   The span is represented as a tuple of (start, end), which is a half-open
   range using unicode offsets.

   Every match with a span must have a string. (If nothing else, the string
   can be the contents at that span location.)

Note that the :attr:`string` may be *different* than the actual textual content
at the :attr:`span` destination. For example, consider the Python expression
``(b + c) * d``. If we have a match for the addition operation, it might have a
:attr:`string` of ``"b + c"``, but a span that is ``"(b + c)"``.
This is a useful thing to do:

1) If we replace this expression with ``"e"``, it would be nice for the
   expression to become ``e * d``, rather than ``(e) * d``.
2) If we substitute this match into a function call, it would be nice for
   that call to become ``foo(b + c)`` rather than ``foo((b + c))``.
"""

from __future__ import absolute_import
from __future__ import division
# from __future__ import google_type_annotations
from __future__ import print_function

from typing import Any, Tuple

import attr


@attr.s(frozen=True)
class Match(object):
  """A match with no accompanying information.

  .. attribute:: string
  .. attribute:: span
  """

  string = None
  span = None


@attr.s(frozen=True)
class StringMatch(Match):
  """A match which can be a source for substitution.

  .. attribute:: string
  .. attribute:: span"""
  string = attr.ib()


@attr.s(frozen=True)
class SpanMatch(StringMatch):
  """A match which can be both a source *and* destination for substitution.

  .. attribute:: string
  .. attribute:: span"""
  span = attr.ib()

  @classmethod
  def from_text(cls, text: str, span: Tuple[int, int]) -> "SpanMatch":
    """Creates a :class:`SpanMatch` from a span within ``text``."""
    start, end = span
    return SpanMatch(string=text[start:end], span=span)


@attr.s(frozen=True)
class ObjectMatch(Match):
  """Match that carries data with it, but has no associated span or string.

  .. attribute:: string
  .. attribute:: span
  """
  #: An object associated with the match.
  matched = attr.ib()  # type: Any
