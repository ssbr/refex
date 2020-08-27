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

# Lint as: python3
"""Pretty-print rxerr_*.json files."""

import json
import shlex
import sys
import tempfile

import pygments
from pygments import formatters
from pygments import lexers


def main(argv):
  if len(argv) != 2:
    sys.exit('Expected exactly 1 argument, got: %s' % (len(argv) - 1))
  debug_file = argv[-1]
  with open(debug_file) as f:
    debug_info = json.load(f)

  rxerr_argv = debug_info.get('argv')
  if rxerr_argv:
    print('Command:', ' '.join(shlex.quote(arg) for arg in rxerr_argv), '\n')
  is_first = False
  for f, failure in debug_info.get('failures', {}).items():
    if not is_first:
      print('\n')
    is_first = False

    print('File:', f)
    try:
      source = failure['content']
    except KeyError:
      pass
    with tempfile.NamedTemporaryFile(
        mode='w', encoding='utf-8', suffix='.py', delete=False) as out_f:
      out_f.write(source)
      print('Content:', out_f.name)
    try:
      tb = failure['traceback']
    except KeyError:
      pass
    else:
      print(
          pygments.highlight(tb, lexers.PythonTracebackLexer(),
                             formatters.Terminal256Formatter()))


if __name__ == '__main__':
  main(sys.argv)
