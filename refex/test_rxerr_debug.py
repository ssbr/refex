"""Tests for refex.rxerr_debug."""

import contextlib
import io
import json
import shlex

from absl.testing import absltest

from refex import rxerr_debug


class RxerrDebugTest(absltest.TestCase):

  def test_argv(self):
    """Tests that argv is output in a copy-pasteable way (best as possible)."""
    argv = ['refex', """complex\n"arg'ument"""]
    path = self.create_tempfile(content=json.dumps({'argv': argv})).full_path
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
      rxerr_debug.main(['rxerr_debug', path])

    # not hardcoding the string because there's many different ways to do it,
    # and shlex.quote has bad-ish formatting that may improve in future.
    # For example, on Python 3.8, I get:
    #   >>> import shlex; print(shlex.join(['a', 'b" c' "'"]))
    #   a 'b" c'"'"''
    # (the trailing '' is superfluous.)
    # Instead, we can just run shlex.split() over it as a quick safety check.
    self.assertEqual(shlex.split(stdout.getvalue()), ['Command:'] + argv)


if __name__ == '__main__':
  absltest.main()
