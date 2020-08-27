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
"""Human-readable error messages for exceptions."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function


def _indent(s):
  return ''.join('    ' + line for line in s.splitlines(True))


def user_syntax_error(e, source_code):
  """Returns a representation of the syntax error for human consumption.

  This is only meant for small user-provided strings. For input files,
  prefer the regular Python format.

  Args:
    e: The SyntaxError object.
    source_code: The source code.

  Returns:
    A multi-line error message, where the first line is the summary, and the
    following lines explain the error in more detail.
  """

  summary = 'Failed to parse Python-like source code ({msg}).'.format(
      msg=e.msg or '<unknown reason>')
  if e.text is None:
    # Only output the source code.
    return '\n'.join([summary, _indent(source_code)])
  # Alternatively, we could use the middle two lines from
  # traceback.format_exception_only(SyntaxError, e), but it isn't clear that
  # this is an improvement in terms of maintainability. (e.g. we do not then
  # control the indent, and if the format changes in the future the output
  # becomes nonsense).
  error_information = '\n'.join([
      e.text.rstrip('\r\n'),  # \n is added by ast.parse but not exec/eval.
      ' ' * (e.offset - 1) + '^',  # note: offset is 1-based.
  ])

  if '\n' in source_code:
    return '\n'.join([
        summary,
        '',
        'Source:',
        _indent(source_code),
        '',
        'Location:',
        _indent(error_information),
    ])
  else:
    return '\n'.join([summary, _indent(error_information)])
