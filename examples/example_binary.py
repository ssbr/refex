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
"""An example binary using refex.cli.run() to run a preprogrammed search/replace.

This is similar in functionality to a shell script that runs:

    refex --mode=py.expr hello --sub=world -i "$@"
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import sys

from refex import cli
from refex import search
from refex.python import syntactic_template
from refex.python.matchers import syntax_matchers


def main():
  cli.run(
      runner=cli.RefexRunner(
          searcher=search.PyExprRewritingSearcher.from_matcher(
              # --mode=py.expr is equivalent to PyExprRewritingSearcher paired
              # with an ExprPattern. However, you can pass any matcher, not just
              # an ExprPattern.
              syntax_matchers.ExprPattern('hello'),
              {
                  # Using ROOT_LABEL as a key is equivalent to --sub=world.
                  # To get the equivalent of --named-sub=x=world,
                  # it would 'x' as a key instead.
                  #
                  # The value type corresponds to the --sub-mode. While
                  # refex on the command line defaults to picking the paired
                  # --sub-mode that matches the --mode, here there are no
                  # defaults and you must be explicit.
                  # e.g. for unsafe textual substitutions, as with
                  # --sub-mode=sh, you would use formatting.ShTemplate.
                  search.ROOT_LABEL:
                      syntactic_template.PythonExprTemplate('world')
              },
          ),
          dry_run=False,
      ),
      files=sys.argv[1:],
      bug_report_url='<project bug report URL goes here>',
  )

if __name__ == '__main__':
  main()
