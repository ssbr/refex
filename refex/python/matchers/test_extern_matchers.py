# Copyright 2021 Google LLC
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
"""Tests for refex.matchers.extern_matchers."""

from absl.testing import absltest

from refex import search
from refex.python import matcher_test_util
from refex.python.matchers import extern_matchers


def _rewrite(m, code):
  return search.rewrite_string(
      search.PyMatcherRewritingSearcher.from_matcher(m, {}), code, 'example.py')


class RewriteFileTest(matcher_test_util.MatcherTestCase):

  def test_rewrite_fail(self):

    class Fail(extern_matchers.RewriteFile):

      def rewrite(self, context, candidate):
        return None

    self.assertEqual(_rewrite(Fail('metavar'), 'old'), 'old')

  def test_rewrite_succeed(self):

    class Succeed(extern_matchers.RewriteFile):

      def rewrite(self, context, candidate):
        return 'new'

    self.assertEqual(_rewrite(Succeed('metavar'), 'old'), 'new')


class ExternalCommandTest(matcher_test_util.MatcherTestCase):

  def test_replace_noop(self):
    code = '1\n2\n'
    self.assertEqual(
        _rewrite(extern_matchers.ExternalCommand('cat', ['cat']), code), code)

  def test_replace(self):
    code = '1\n2\n'
    self.assertEqual(
        _rewrite(
            extern_matchers.ExternalCommand('echo', ['echo', 'hello']), code),
        'hello\n')

  def test_shell_true(self):
    code = '1\n2\n'
    self.assertEqual(
        _rewrite(
            extern_matchers.ExternalCommand('echo', 'echo hello', shell=True),
            code), 'hello\n')


if __name__ == '__main__':
  absltest.main()
