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
"""Tests for refex.fix.fixers.modern_python_fixers."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from absl.testing import absltest
from absl.testing import parameterized

from refex import search
from refex.fix.fixers import modern_python_fixers


def _rewrite(fixer, source):
  return search.rewrite_string(fixer, source, 'example.py')


class ModernPythonFixersTest(parameterized.TestCase):

  def test_fix_dict_has_key(self):
    fixer = modern_python_fixers._HAS_KEY_FIXER
    before = '{}.has_key(1)'
    expected = '1 in {}'
    self.assertEqual(expected, _rewrite(fixer, before))

  def test_fix_dict_iteritems(self):
    fixer = modern_python_fixers._dict_iter_fixer('iteritems')
    before = 'import six; d.iteritems()'
    expected = 'import six; six.iteritems(d)'
    self.assertEqual(expected, _rewrite(fixer, before))


if __name__ == '__main__':
  absltest.main()
