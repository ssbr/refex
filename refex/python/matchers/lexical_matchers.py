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
:mod:`~refex.python.matchers.lexical_matchers`
----------------------------------------------

:mod:`~refex.python.matchers.lexical_matchers` provides lexical tweaks and
filters on lexical matches.

.. autoclass:: HasComments
.. autoclass:: NoComments

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tokenize

import attr

from refex.python import matcher


@matcher.safe_to_eval
@attr.s(frozen=True)
class HasComments(matcher.Matcher):
  """Filter results to only those lexical spans that have comments inside.

  Args:
    submatcher: A Matcher matching a LexicalMatch.
  """
  _submatcher = matcher.submatcher_attrib()  # type: matcher.Matcher

  def _match(self, context, candidate):
    result = self._submatcher.match(context, candidate)
    if _result_has_comments(context, self._submatcher, result):
      return result
    else:
      return None


@matcher.safe_to_eval
@attr.s(frozen=True)
class NoComments(matcher.Matcher):
  """Filter results to only those lexical spans that have no comments inside.

  Args:
    submatcher: A Matcher matching a LexicalMatch.
  """
  _submatcher = matcher.submatcher_attrib()  # type: matcher.Matcher

  def _match(self, context, candidate):
    result = self._submatcher.match(context, candidate)
    if _result_has_comments(context, self._submatcher, result):
      return None
    else:
      return result


# TODO(b/64560910): Yield all the comments so that matchers can operate on them
# and check what they contain.
def _result_has_comments(context, m, result):
  """Returns whether or not there are spans in a result."""
  if result is None:
    # Doesn't actually matter either way -- anyone checking will return either
    # result, or None, and here both are None. But if we ask the question,
    # "does there exist at least one comment node we can find here?" the answer
    # is no.
    return False
  if not isinstance(result.match, matcher.LexicalMatch):
    raise TypeError(
        'Expected a LexicalMatch from matcher (%r), got: %r' % (m, result))

  first_token = result.match.first_token
  last_token = result.match.last_token
  for token in context.parsed_file.ast_tokens.token_range(
      first_token, last_token, include_extra=True):
    if token.type == tokenize.COMMENT:
      return True
  return False
