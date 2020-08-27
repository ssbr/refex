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
"""Outputs an example file full of things to fix."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys

from refex.fix import find_fixer


def example_source():
  lines = []
  lines.append(u'# coding: utf-8')
  lines.append(u'# Only enable refex warnings: pylint: skip-file')
  for fx in find_fixer.from_pattern('*').fixers:
    lines.append(fx.example_fragment())
  lines.append(u'')
  return u'\n'.join(lines).encode('utf-8')


def main():
  if len(sys.argv) > 1:
    sys.exit('Too many command-line arguments.')
  print(example_source().decode('utf-8'), end='')


if __name__ == '__main__':
  main()
