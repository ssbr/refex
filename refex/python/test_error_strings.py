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
"""Tests for refex.python.error_strings."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import ast
import textwrap

from absl.testing import absltest

from refex.python import error_strings


def _user_syntax_error_string(source_code):
  try:
    ast.parse(source_code)
  except SyntaxError as e:
    return error_strings.user_syntax_error(e, source_code)
  else:
    raise AssertionError("Didn't fail to parse: %s" % source_code)


class UserSyntaxErrorTest(absltest.TestCase):

  def test_long(self):
    self.assertEqual(
        _user_syntax_error_string('xyz\na b'),
        textwrap.dedent("""\
                         Failed to parse Python-like source code (invalid syntax).

                         Source:
                             xyz
                             a b

                         Location:
                             a b
                               ^"""))

  def test_short(self):
    self.assertEqual(
        _user_syntax_error_string('a b'),
        textwrap.dedent("""\
                         Failed to parse Python-like source code (invalid syntax).
                             a b
                               ^"""))

  def test_synthetic_error_long(self):
    """User-synthesized SyntaxErrors still give nice output."""
    self.assertEqual(
        error_strings.user_syntax_error(SyntaxError('message'), 'a\nb'),
        textwrap.dedent("""\
                         Failed to parse Python-like source code (message).
                             a
                             b"""))

  def test_synthetic_error_short(self):
    self.assertEqual(
        error_strings.user_syntax_error(SyntaxError('message'), 'a b'),
        textwrap.dedent("""\
                         Failed to parse Python-like source code (message).
                             a b"""))

  def test_synthetic_error_no_msg(self):
    self.assertEqual(
        error_strings.user_syntax_error(SyntaxError(''), 'a b'),
        textwrap.dedent("""\
                         Failed to parse Python-like source code (<unknown reason>).
                             a b"""))


if __name__ == '__main__':
  absltest.main()
