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

from absl import app

# Hack to get flags parsed -- both absl and the test runner expect to own main().
# Fortunately, absl doesn't de-construct state after main finishes, so we
# can pretend to give it what it wants.
try:
  app.run(lambda argv: None)
except SystemExit:
  # neener neener
  pass
