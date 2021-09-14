"""Tests for refex.rxerr_debug."""

import io
import json
import shlex

from absl.testing import absltest
import contextlib
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

  def test_traceback(self):
    """Tests that the traceback shows up, ish."""
    tb = ('Traceback (most recent call last):\n'
          '  File "<stdin>", line 1, in <module>\n'
          'SomeError: description\n')
    path = self.create_tempfile(
        content=json.dumps({'failures': {
            'path': {
                'traceback': tb
            }
        }})).full_path
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
      rxerr_debug.main(['rxerr_debug', path])
    stdout = stdout.getvalue()
    self.assertIn('SomeError', stdout)
    self.assertIn('description', stdout)


if __name__ == '__main__':
  absltest.main()
