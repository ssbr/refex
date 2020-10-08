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

# python3
"""A simple test of the example binary."""

import subprocess
import sys

from absl.testing import absltest

_EXECUTABLE = [sys.executable, 'examples/example_binary.py']


class RefexBinaryTest(absltest.TestCase):

  def test_binary(self):
    f = self.create_tempfile(content='hello')
    subprocess.check_call(_EXECUTABLE + [f.full_path])
    self.assertEqual(f.read_text(), 'world')


if __name__ == '__main__':
  absltest.main()
