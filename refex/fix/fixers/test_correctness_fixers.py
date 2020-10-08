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

# Lint as python2, python3
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import textwrap

from absl.testing import absltest
from absl.testing import parameterized

from refex import search
from refex.fix import fixer
from refex.fix.fixers import correctness_fixers


def _rewrite(fixer_, code):
  return search.rewrite_string(fixer_, code, 'example.py')


class SimpleFixersTest(parameterized.TestCase):
  fixers = fixer.CombiningPythonFixer(correctness_fixers.SIMPLE_PYTHON_FIXERS)

  def test_skips_number_mod(self):
    before = 'y = 3 % (x)'
    self.assertEqual(before, _rewrite(self.fixers, before))

  @parameterized.parameters('(\nfoo)', '(foo\n)', '(foo\n.bar)')
  def test_skips_multiline_rhs(self, rhs):
    before = 'y = "hello %s" % {rhs}'.format(rhs=rhs)
    self.assertEqual(before, _rewrite(self.fixers, before))

  def test_skips_formatting_when_already_using_tuple(self):
    before = "y = 'hello %s' % (world,)"
    self.assertEqual(before, _rewrite(self.fixers, before))

  @parameterized.parameters('u', 'b', '')
  def test_changes_superfluous_parens_to_tuple_when_formatting(
      self, string_prefix):
    before = textwrap.dedent("""
       y = (
         {}'hello: %s\\n' % (thing.world))
    """).format(string_prefix)
    after = textwrap.dedent("""
       y = (
         {}'hello: %s\\n' % (thing.world,))
    """).format(string_prefix)
    self.assertEqual(after, _rewrite(self.fixers, before))


if __name__ == '__main__':
  absltest.main()
