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
"""Tests for refex.parsed_file."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from absl.testing import absltest
from absl.testing import parameterized

from refex import parsed_file


class PragmaTest(parameterized.TestCase):

  @parameterized.parameters(
      u'stuff before the tag: t:a=b,c=d',
      u't:a=b,c=d',
      u' t:a=b,c=d',
      u't :a=b,c=d',
      u't: a=b,c=d',
      u't:a =b,c=d',
      u't:a= b,c=d',
      u't:a=b ,c=d',
      u't:a=b, c=d',
      u't:a=b,c =d',
      u't:a=b,c= d',
      u't:a=b,c=d ',
      u't:a=b,c=d,',
      u't:a=b,c=d ,',
      u't:a=b,c=d, ',
  )
  def test_from_text(self, text):
    pragma = parsed_file.Pragma.from_text(text, 0, 100)
    self.assertIsNotNone(pragma)
    self.assertEqual(pragma.tag, u't')
    self.assertEqual(pragma.data, {u'a': u'b', u'c': u'd'})

  def test_from_text_long(self):
    """Tests multi-character words in from_text, using a realistic example."""
    pragma = parsed_file.Pragma.from_text(
        u'foo bar baz: pylint: disable=broad-except', 0, 100)
    self.assertIsNotNone(pragma)
    self.assertEqual(pragma.tag, u'pylint')
    self.assertEqual(pragma.data, {u'disable': u'broad-except'})

  def test_from_text_dotted(self):
    pragma = parsed_file.Pragma.from_text(
        u'refex: disable=pylint.broad-except', 0, 100)
    self.assertIsNotNone(pragma)
    self.assertEqual(pragma.tag, u'refex')
    self.assertEqual(pragma.data, {u'disable': u'pylint.broad-except'})

  @parameterized.parameters(
      u't a=b',
      u':a=b',
      u't:',
      u't:a a=b',
      u't:a=b b',
      u't:a=b=b',
      u't:ab',
      u't:a=',
      u't:=b',
  )
  def test_from_text_fails(self, text):
    self.assertIsNone(parsed_file.Pragma.from_text(text, 0, 100))


if __name__ == '__main__':
  absltest.main()
