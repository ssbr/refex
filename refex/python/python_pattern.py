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
"""Parsing of Python patterns containing metavariables.

For example: "a = $b" is a pattern for an assignment statement, where the target
is a wildcard named "b".
"""

import io
import re
import token
import tokenize


_VARIABLE_REGEX = re.compile(r'\A[a-zA-Z_][a-zA-Z0-9_]*\Z')


def token_pattern(
    pattern: str,
) -> tuple[list[tokenize.TokenInfo], set[int], set[int]]:
  """Tokenizes a source pattern containing metavariables like "$foo".

  The following special forms are accepted:

  * Matches anything once, binding to the name ``foo``: ``$foo``.
  * Matches anything ``n`` times, binding to the name ``bars``: ``$bars...``.
  * Matches anything ``n`` times, binding to the name ``_``: ``$...``.

  (The repeated matching syntax makes the assumption that there's no useful
  place in _Python_ for an identifier to be followed directly by a ``...``. If,
  one day, Python allows an identifier directly followed by a ``...``, this is
  possible to handle by extending the pattern syntax to match this via e.g.
  ``${x}...`` vs ``${x...}``. However, this would not be a desirable state of
  affairs.)

  Args:
    pattern: A Python source pattern.

  Returns:
    (tokenized, nonrepeating_metavar_indices, repeating_metavar_indices).
    tokenized:
      A list of source tokens, omitting the metavariable marker ($).
    nonrepeating_metavar_indices:
      A set of token indexes. tokenized[i] is a nonrepeating metavariable token
      if and only if i is in nonrepeating_metavar_indices.
    repeating_metavar_indices:
      A set of token indexes. tokenized[i] is a repeating metavariable token
      if and only if i is in repeating_metavar_indices.

  Raises:
    SyntaxError: The pattern can't be parsed.
  """
  # A note on column spans:
  #
  # untokenize() uses the gap between the end_col of the last token and the
  # start_col of the next token to decide how many spaces to put -- there is no
  # "space token". As a result, if we do nothing, in the expression `$x...`,
  # the `$` and the `...` will each be filled with spaces when the `$` and `...`
  # tokens are removed, even if `x` is replaced with a long token string such
  # as `foooooo`. To prevent this, we must mutate the start/end cols, resulting
  # in tokens with a string value shorter than the col span.

  # Work around Python 3.6.7's newline requirement.  See b/118359498.
  if pattern.endswith('\n'):
    added_newline = False
  else:
    added_newline = True
    pattern += '\n'

  try:
    tokens = list(tokenize.generate_tokens(io.StringIO(pattern).readline))
  except tokenize.TokenError as e:
    raise SyntaxError("Couldn't tokenize %r: %s" % (pattern, e)) from None

  retokenized = []
  nonrepeating_metavar_indices = set()
  repeating_metavar_indices = set()

  tokens_it = iter(tokens)
  for tok in tokens_it:
    if tok[1] == '...':
      # If the last token was a nonrepeating variable, upgrade it to repeating.
      # otherwise, add `...`.
      last_token_index = len(retokenized) - 1
      if last_token_index in nonrepeating_metavar_indices:
        last_token = retokenized[last_token_index]
        if last_token.end != tok.start:
          raise SyntaxError(
              f'No spaces allowed between metavariable and `...`: {pattern!r}'
          )
        retokenized[last_token_index] = last_token._replace(end=tok.end)
        nonrepeating_metavar_indices.remove(last_token_index)
        repeating_metavar_indices.add(last_token_index)
      else:
        retokenized.append(tok)
    elif tok[1] != '$':
      # Just a note: in the presence of errors, even whitespace gets added as
      # error tokens, so we're including that here on purpose.
      retokenized.append(tok)
    else:
      assert tok[0] == token.ERRORTOKEN
      try:
        variable_token = next(tokens_it)
      except StopIteration:
        # This should never happen, because we get an ENDMARKER token.
        # But who knows, the token stream may change in the future.
        raise SyntaxError('Expected variable after $, got EOF') from None
      if variable_token.string == '...':
        is_repeated = True
        variable_token = variable_token._replace(string='_')
      elif _VARIABLE_REGEX.match(variable_token.string):
        is_repeated = False
      else:
        raise SyntaxError(
            'Expected variable name or ``...`` after $, but next token'
            f" {variable_token.string!r} wasn't /{_VARIABLE_REGEX.pattern}/"
            ' or ...'
        )

      if tok.end != variable_token.start:
        raise SyntaxError(
            f'No spaces allowed between $ and next token: {pattern!r}'
        )
      variable_token = variable_token._replace(start=tok.start)
      if is_repeated:
        repeating_metavar_indices.add(len(retokenized))
      else:
        nonrepeating_metavar_indices.add(len(retokenized))
      retokenized.append(variable_token)

  # Undo damage required to work around Python 3.6.7's newline requirement
  # See b/118359498 for details.
  if added_newline and len(retokenized) >= 2 and retokenized[-2][1] == '\n':
    del retokenized[-2]
  return retokenized, nonrepeating_metavar_indices, repeating_metavar_indices
