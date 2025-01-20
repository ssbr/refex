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


def token_pattern(pattern):
  """Tokenizes a source pattern containing metavariables like "$foo".

  Args:
    pattern: A Python source pattern.

  Returns:
    (tokenized, metavar_indices).
    tokenized:
      A list of source tokens, omitting the metavariable marker ($).
    metavar_indices:
      A set of token indexes. tokenized[i] is a metavariable token if and only
      if i is in metavar_indices.

  Raises:
    SyntaxError: The pattern can't be parsed.
  """
  # Work around Python 3.6.7's newline requirement.  See b/118359498.
  if pattern.endswith('\n'):
    added_newline = False
  else:
    added_newline = True
    pattern += '\n'

  try:
    tokens = list(tokenize.generate_tokens(io.StringIO(pattern).readline))
  except tokenize.TokenError as e:
    raise SyntaxError("Couldn't tokenize %r: %s" % (pattern, e)) from e

  retokenized = []
  metavar_indices = set()

  tokens_it = iter(tokens)
  for tok in tokens_it:
    if tok.string != '$':
      # Just a note: in the presence of errors, even whitespace gets added as
      # error tokens, so we're including that here on purpose.
      retokenized.append(tok)
    else:
      assert tok.type in (token.ERRORTOKEN, token.OP)
      try:
        variable_token = next(tokens_it)
      except StopIteration:
        # This should never happen, because we get an ENDMARKER token.
        # But who knows, the token stream may change in the future.
        raise SyntaxError('Expected variable after $, got EOF')
      variable = variable_token.string
      if not _VARIABLE_REGEX.match(variable):
        raise SyntaxError(
            "Expected variable after $, but next token (%r) didn't match %s" %
            (variable, _VARIABLE_REGEX.pattern))

      start_row, start_col = variable_token.start
      # untokenize() uses the gap between the end_col of the last token and the
      # start_col of this token to decide how many spaces to put -- there is no
      # "space token". As a result, if we do nothing, the place where the "$"
      # was will become a space. This is usually fine, but causes phantom
      # indents and syntax errors if the $ was the first character on the line.
      # e.g. it could not even parse the simple expression "$foo"
      # To avoid this, we must remove 1 from start_col to make up for it.
      if tok.start[1] != start_col - 1:
        # newlines get a NL token, so we only need to worry about columns.
        raise SyntaxError('No spaces allowed between $ and variable name: %r' %
                          pattern)
      metavar_indices.add(len(retokenized))
      retokenized.append(variable_token._replace(
          start=(start_row, start_col - 1)))

  # Undo damage required to work around Python 3.6.7's newline requirement
  # See b/118359498 for details.
  if added_newline and len(retokenized) >= 2 and retokenized[-2][1] == '\n':
    del retokenized[-2]
  return retokenized, metavar_indices
