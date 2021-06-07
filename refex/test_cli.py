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
"""Tests for cli."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import argparse
import contextlib
import json
from unittest import mock
import os
import re
import sys
import textwrap
import unittest

from absl.testing import absltest
from absl.testing import parameterized
import six

from refex import cli


class ParseArgsLeftoversTest(absltest.TestCase):

  def test_extra_arg(self):
    """The simplest test: something that doesn't look like a flag at the end."""
    parser = argparse.ArgumentParser()
    _, leftovers = cli._parse_args_leftovers(parser, ['x'])
    self.assertEqual(leftovers, ['x'])

  def test_unknown_args(self):
    parser = argparse.ArgumentParser()
    with self.assertRaises(SystemExit):
      with contextlib.redirect_stderr(six.StringIO()) as fake_stderr:
        cli._parse_args_leftovers(
            parser, ['x', '--unknown-arg', 'y', '--unknown-arg2', 'z'])
    self.assertEndsWith(
        fake_stderr.getvalue(),
        'unrecognized arguments: --unknown-arg --unknown-arg2\n')
    self.assertIn('usage: ', fake_stderr.getvalue())

  def test_escaped_args(self):
    parser = argparse.ArgumentParser()
    _, leftovers = cli._parse_args_leftovers(parser,
                                             ['x', '--', '--unknown-arg'])
    self.assertEqual(leftovers, ['x', '--unknown-arg'])

  def test_interleaved_args(self):
    parser = argparse.ArgumentParser()
    parser.add_argument('--foo')
    parser.add_argument('--bar')
    options, leftovers = cli._parse_args_leftovers(
        parser, ['x', '--foo=foo', 'y', '--bar=bar', 'z'])
    self.assertEqual(leftovers, ['x', 'y', 'z'])
    self.assertEqual(options.foo, 'foo')
    self.assertEqual(options.bar, 'bar')

  def test_conflicting_escaped_args(self):
    parser = argparse.ArgumentParser()
    parser.add_argument('--foo')
    options, leftovers = cli._parse_args_leftovers(
        parser, ['--foo=foo', '--', '--foo=bar'])
    self.assertEqual(leftovers, ['--foo=bar'])
    self.assertEqual(options.foo, 'foo')


class ExceptionTest(absltest.TestCase):

  def test_excepthook(self):
    err = six.StringIO()
    try:
      raise ZeroDivisionError('Hello world.')
    except ZeroDivisionError:
      excepthook_args = sys.exc_info()

    with cli._report_bug_excepthook('BUG_REPORT_URL'):
      hook = sys.excepthook
    with contextlib.redirect_stderr(err):
      hook(*excepthook_args)
    self.assertRegex(
        err.getvalue(),
        r'Traceback(?:\n|.)*\nZeroDivisionError: Hello world\.\nIs this a bug\?'
        r' .*BUG_REPORT_URL\n')


class MainTestBase(parameterized.TestCase):
  """Base class for tests that invoke the main function directly.

  Since it's possible to write a new main based on the extension points in cli,
  users who do so may want to also inherit the same tests. There should be
  relatively few subclasses in cli_test.
  """

  def raw_main(self, argv):
    """Runs the main function directly. Overridden by subclasses."""
    return cli.main(argv)

  def main(self, args):
    """Runs raw_main configured for testing, and returns stdout.

    Args:
      args: The trailing argv for this invocation, minus argv[0] and arguments
        intended to aid all tests.

    Returns:
      The output to stdout of main(), as a string.
    """
    # default to nocolor so that tests run the same on all systems.
    # default to verbose so that you don't need to run rxerr_debug if there's
    # an exception during testing. (Especially difficult if e.g. the test
    # was run in cloud CI or something which doesn't let you download the file.)
    argv = ['refex', '--nocolor', '--verbose'] + args
    with contextlib.redirect_stdout(six.StringIO()) as fake_stdout:
      try:
        self.raw_main(argv)
      except SystemExit as e:
        if e.code:
          raise
    return fake_stdout.getvalue()

  def assert_main_error(self, argv):
    """Asserts that main fails, and returns the SystemExit.code."""
    with mock.patch.object(argparse.ArgumentParser, 'error',
                           lambda self, message: sys.exit(message)):
      try:
        self.raw_main(['refex'] + argv)
      except SystemExit as e:
        if e.code is not None and e.code != 0:
          return e.code
    self.fail('Refex did not fail when given these args: {}'.format(argv))


class MainTest(MainTestBase):

  def test_unknown_args(self):
    """Tests that unknown arguments cause an error."""
    with self.assertRaises(SystemExit):
      with contextlib.redirect_stderr(six.StringIO()) as fake_stderr:
        self.main(['--mode=re', 'pattern', '--unknown-arg', '--unknown-arg2'])
    self.assertEndsWith(
        fake_stderr.getvalue(),
        'unrecognized arguments: --unknown-arg --unknown-arg2\n')
    self.assertIn('usage: ', fake_stderr.getvalue())

  def test_grep_with_filename(self):
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    for extra_flags in [[], ['--with-filename'],
                        [
                            '--no-filename',
                            '--with-filename',
                        ]]:
      output = self.main(['--mode=re', 'xyzzy'] + extra_flags + [f.full_path])
      output_lines = output.splitlines()
      self.assertLen(output_lines, 2)
      self.assertEqual(os.path.abspath(output_lines[0]), f.full_path)
      self.assertEqual(output_lines[1], 'xx xyzzy xx')

  @parameterized.parameters('xyzzy', '(xyzzy)')
  def test_grep_with_filename_color(self, regex):
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    output = self.main(
        ['--mode=re', regex, '--with-filename', '--color=always', f.full_path])
    self.assertRegex(
        output, '.+%s.+\nxx .+xyzzy.+ xx\n' % os.path.basename(f.full_path))

  def test_grep_no_filename(self):
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    for extra_flags in ['--no-filename'], ['--with-filename', '--no-filename']:
      output = self.main(['--mode=re', 'xyzzy'] + extra_flags + [f.full_path])
      self.assertEqual(output, 'xx xyzzy xx\n')

  def test_grep_multi(self):
    f = self.create_tempfile(content='a\nb\n')
    self.assertEqual(
        self.main(['--mode=re', '[ab]', '--no-filename', f.full_path]),
        'a\nb\n',
    )

  def test_grep_zero_width_match(self):
    """A zero width match still shows the whole line."""
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    output = self.main(['--mode=re', '(?=xyzzy)', '--no-filename', f.full_path])
    self.assertEqual(output, 'xx xyzzy xx\n')

  def test_grep_also_nomatch(self):
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    output = self.main(
        ['--mode=re', 'xyzzy', '--also=not present', f.full_path])
    self.assertEqual(output, '')

  def test_grep_also_match(self):
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    output = self.main(
        ['--mode=re', 'xyzzy', '--also=abc', '--no-filename', f.full_path])
    self.assertEqual(output, 'xx xyzzy xx\n')

  def test_grep_noalso_nomatch(self):
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    output = self.main([
        '--mode=re', 'xyzzy', '--noalso=not present', '--no-filename',
        f.full_path
    ])
    self.assertEqual(output, 'xx xyzzy xx\n')

  def test_grep_noalso_match(self):
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    output = self.main(['--mode=re', 'xyzzy', '--noalso=abc', f.full_path])
    self.assertEqual(output, '')

  def test_grep_list(self):
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    output = self.main(['--mode=re', 'xyzzy', '-l', f.full_path])
    self.assertEqual(os.path.abspath(output.rstrip('\r\n')), f.full_path)

  def test_grep_include(self):
    included_f = self.create_tempfile()
    output = self.main([
        '--mode=re',
        '.*',
        '--includefile=.*',
        '-l',
        included_f.full_path,
        'excluded_file_path',
    ])
    output_lines = output.splitlines()
    self.assertLen(output_lines, 1)
    self.assertEqual(os.path.abspath(output_lines[0]), included_f.full_path)

  def test_grep_exclude(self):
    included_f = self.create_tempfile()
    output = self.main([
        '--mode=re', '.*', '--excludefile=excluded_file_path', '-l',
        included_f.full_path, 'excluded_file_path'
    ])
    output_lines = output.splitlines()
    self.assertLen(output_lines, 1)
    self.assertEqual(os.path.abspath(output_lines[0]), included_f.full_path)

  @parameterized.parameters('--format={match}', '-o', '--only-matching')
  def test_grep_format(self, format_arg):
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    output = self.main(
        ['--mode=re', 'xyzzy', format_arg, '--no-filename', f.full_path])
    self.assertEqual(output, 'xyzzy\n')

  def test_grep_multiline_start(self):
    f = self.create_tempfile(
        content='first line\nxyzzy\nabc xyzzy\nlast line\n')
    output = self.main(['--mode=re', '^xyzzy', '--no-filename', f.full_path])
    self.assertEqual(output, 'xyzzy\n')

  def test_grep_multiline_end(self):
    f = self.create_tempfile(
        content='first line\nxyzzy\nxyzzy abc\nlast line\n')
    output = self.main(['--mode=re', 'xyzzy$', '--no-filename', f.full_path])
    self.assertEqual(output, 'xyzzy\n')

  def test_sub_empty(self):
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    output = self.main(
        ['--mode=re', 'xyzzy', '--sub=', '--no-filename', f.full_path])
    self.assertRegex(output, r'-xx xyzzy xx\n' r'\+xx  xx\n')

  def test_sub_named_group(self):
    """Named groups are available under both their name and their index."""
    f = self.create_tempfile(content='abc')
    _ = self.main(
        ['--mode=re', r'(?P<name>a)bc', r'--sub=\g<name>\1', '-i', f.full_path])
    self.assertEqual(f.read_text(), 'aa')

  def test_sub_extra_groups(self):
    message = self.assert_main_error(
        ['--mode=re', 'xyzzy', r'--sub=\1 \g<foo>', os.devnull])
    self.assertEqual(
        message,
        'The substitution template(s) referenced groups not available in the regex (`xyzzy`): `1`, `foo`'
    )

  def test_sub_diff_with_unchanged(self):
    """Tests sub diffs with unchanged lines."""
    f = self.create_tempfile(
        content=textwrap.dedent("""
        a
        aba
        a
        """))
    output = self.main([
        '--mode=re', 'a\na(?P<b>b)a\na', '--named-sub=b=', '--no-filename',
        f.full_path
    ])
    self.assertStartsWith(output, ' a\n-aba\n+aa\n a\n')
    self.assertStartsWith(
        output,
        textwrap.dedent("""\
         a
        -aba
        +aa
         a
        """))

  def test_sub_diff_with_unchanged_multiline(self):
    """Tests that unchanged portions are allocated to the correct diff blocks.

    In particular, there's a possible corner case with a diff like this:

     a
    -aba
    +aa
     a
    -aba
    +aa

   Where we want the unchanged "a" in the middle to not be allocated to
   either diff block.
   """
    f = self.create_tempfile(
        content=textwrap.dedent("""
        a
        aba
        a
        aba
        """))
    regex = textwrap.dedent("""\
        a
        a(?P<b1>b)a
        a
        a(?P<b2>b)a
        """)
    output = self.main([
        '--mode=re', regex, '--named-sub=b1=', '--named-sub=b2=',
        '--no-filename', f.full_path
    ])
    self.assertStartsWith(
        output,
        textwrap.dedent("""\
         a
        -aba
        +aa
         a
        -aba
        +aa
        """))

  def test_sub_overlap(self):
    f = self.create_tempfile(content='a\nab')
    output = self.main([
        '--mode=re', '(?P<a>a\na)(?P<b>b)', '--named-sub=a=1',
        '--named-sub=b=2', '--no-filename', f.full_path
    ])
    self.assertStartsWith(
        output,
        textwrap.dedent("""\
        -a
        -ab
        +12
        """))

  @parameterized.parameters(
      # (regex matching everything, replacement referencing unmatched group)
      (r'(xyzzy)?.*', r'\1'),
      (r'(?P<unmatched>xyzzy)?.*', r'\g<unmatched>'))
  def test_sub_unmatched_groups(self, regex, replacement):
    """Unmatched groups are equivalent to empty groups, in regex templates."""
    f = self.create_tempfile(content='abc')
    _ = self.main(
        ['--mode=re', regex,
         '--sub=%s' % replacement, '-i', f.full_path])
    self.assertEqual(f.read_text(), '')

  @parameterized.parameters(
      [[]],
      [['--iterate=10', '--no-iterate']],
  )
  def test_sub_noiterate(self, extra_args):
    f = self.create_tempfile(content='foo')
    _ = self.main(
        ['--mode=py.expr', 'foo', '--sub=wrap(foo)', '-i', f.full_path] +
        extra_args)
    self.assertEqual(f.read_text(), 'wrap(foo)')

  @parameterized.parameters(
      [['--iterate']],
      [['--iterate=3']],
  )
  def test_sub_iterate(self, extra_args):
    f = self.create_tempfile(content='foo')
    _ = self.main(
        ['--mode=py.expr', 'foo', '--sub=wrap(foo)', '-i', f.full_path] +
        extra_args)
    self.assertStartsWith(f.read_text(), 'wrap(wrap(wrap(')
    self.assertEndsWith(f.read_text(), ')))')

  def test_sub_multi(self):
    f = self.create_tempfile(content='a\nb\n')
    _ = self.main([
        '--mode=py.expr',
        '--match=a',
        '--sub=a2',
        '--match=b',
        '--sub=b2',
        f.full_path,
        '-i',
    ])
    self.assertEqual(f.read_text(), 'a2\nb2\n')

  def test_sub_multi_iterate(self):
    # realistic example, taken near-verbatim from the readme
    f = self.create_tempfile(content='self.assertTrue(a == False)')
    _ = self.main([
        '--mode=py.expr',
        '-i',
        '--iterate',
        '--match=self.assertTrue($x == $y)',
        '--sub=self.assertEqual($x, $y)',
        '--match=self.assertEqual($x, False)',
        '--sub=self.assertFalse($x)',
        f.full_path,
    ])
    self.assertEqual(f.read_text(), 'self.assertFalse(a)')

  def test_sub_dryrun(self):
    original_content = 'abc\nxx xyzzy xx'
    f = self.create_tempfile(content=original_content)
    output = self.main(
        ['--mode=re', 'xyzzy', '--sub=QUUX', '--no-filename', f.full_path])
    self.assertRegex(output, r'-xx xyzzy xx\n' r'\+xx QUUX xx\n')
    self.assertEqual(f.read_text(), original_content)

  def test_sub_dryrun_color(self):
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    _ = self.main([
        '--mode=re',
        'xyzzy',
        '--sub=QUUX',
        '--no-filename',
        '--color=always',
        f.full_path,
    ])
    # TODO: Get sub --color working in environments without recent diff
    # binary.
    # This is ridiculous!
    # self.assertRegexpMatches(output,
    # r'.+-xx xyzzy xx.+\n.+\+xx QUUX xx.+\n')

  def test_sub_inplace(self):
    f = self.create_tempfile(content='abc\nxx xyzzy xx')
    output = self.main([
        '--mode=re', 'xyzzy', '--sub=QUUX', '--no-filename', f.full_path, '-i'
    ])
    self.assertRegex(output, r'-xx xyzzy xx\n' r'\+xx QUUX xx\n')
    self.assertEqual(f.read_text(), 'abc\nxx QUUX xx')

  def test_sub_inplace_multi(self):
    f1 = self.create_tempfile(content='xyzzy')
    f2 = self.create_tempfile(content='abc\nxx xyzzy xx')
    _ = self.main([
        '--mode=re', 'xyzzy', '--sub=QUUX', '--no-filename', f1.full_path,
        f2.full_path, '-i'
    ])
    self.assertEqual(f1.read_text(), 'QUUX')
    self.assertEqual(f2.read_text(), 'abc\nxx QUUX xx')

  def test_sub_multiline(self):
    f = self.create_tempfile(content='1\nabc\n2\n')
    output = self.main([
        '--mode=re', r'1\s*abc\s*2', '--sub=QUUX', '--no-filename', '-i',
        f.full_path
    ])
    self.assertEqual(output, '-1\n-abc\n-2\n+QUUX\n')

  def test_sub_multiperline(self):
    """sub shows somewhat confusing output from showing one diff per match."""
    f = self.create_tempfile(content='abc\n')
    output = self.main(
        ['--mode=re', r'[ac]', '--sub=x', '--no-filename', '-i', f.full_path])
    self.assertEqual(output, '-abc\n+xbc\n---\n-abc\n+abx\n')

  def test_named_sub_multi(self):
    f = self.create_tempfile(content='1\n"foo"\n')

    actual = self.main([
        '--mode=py', 'AnyOf(Bind("a", Num()), Bind("b", Str()))',
        '--named-sub=a=X', '--named-sub=b=Y', '--no-filename', '-i', f.full_path
    ])
    expected = '-1\n' '+X\n' '---\n' '-"foo"\n' '+Y\n'
    self.assertEqual(actual, expected)

  def test_named_sub_conflict_sub(self):
    with self.assertRaises(SystemExit):
      self.main(['--mode=py', '_', '--sub=foo', '--named-sub=a=X'])

  def test_named_sub_bad_arg(self):
    with self.assertRaises(SystemExit):
      self.main(['--mode=re', '_', '--named-sub=X'])

  def test_grep_optional_group(self):
    f = self.create_tempfile(content='ab\n')

    output = self.main(['--mode=re', 'ab(c)?', '--no-filename', f.full_path])
    self.assertEqual(output, 'ab\n')

  def test_sub_optional_group(self):
    f = self.create_tempfile(content='ab\n')

    output = self.main([
        '--mode=re', 'ab(c)?', '--no-filename', r'--sub=\1', '-i', f.full_path
    ])
    # Behavior as determined by a poll.
    # This is the Python behavior in sufficiently new versions of Python,
    # and the sed behavior as well.
    # Incidentally, this works automatically: if we keep m.regs as (-1, -1),
    # s[-1:-1] == '', so we're set.
    self.assertEqual(output, '-ab\n')

  def test_silent_skip_missing(self):
    for deleted_file in ['/this/file/doesnt/exist', '/dev']:
      # One file is not present, the other was replaced with an incompatible
      # type. Either way they represent something that we originally thought
      # we could read, but due to subsequent changes (e.g. race conditions)
      # we cannot.
      with self.subTest(file=deleted_file):
        with contextlib.redirect_stderr(six.StringIO()) as fake_stderr:
          output = self.main(['--mode=re', 'xyzzy', deleted_file])
        self.assertEqual(output, '')
        self.assertEqual(fake_stderr.getvalue(), '')

  def test_skip_unreadable_loud(self):
    f = self.create_tempfile(content='xyzzy\n')
    os.chmod(f.full_path, 0)  # Make unreadable.

    with contextlib.redirect_stderr(six.StringIO()) as fake_stderr:
      output = self.main(['--mode=re', 'xyzzy', f.full_path])
    self.assertEqual(output, '')
    self.assertRegex(fake_stderr.getvalue(),
                     'skipped %s: IOError: .*' % re.escape(f.full_path))

  def test_error_reporting(self):
    f = self.create_tempfile(content='42')
    with contextlib.redirect_stderr(six.StringIO()) as fake_stderr:
      self.main([
          '--mode=py', 'Bind("x", TestOnlyRaise("error message"))',
          '--named-sub=x=2', f.full_path
      ])
    lines = fake_stderr.getvalue().splitlines()
    self.assertStartsWith(
        lines[0],
        'skipped %s: TestOnlyRaisedError: error message' % f.full_path)
    self.assertStartsWith(lines[2], 'Traceback')
    lines = lines[-2:]
    self.assertStartsWith(lines[0], 'Encountered 1 error(s)')
    dump = lines[0].rsplit(' ', 1)[-1]
    with open(dump) as dump_f:
      error_dump = json.load(dump_f)
    # Don't care a lot about the traceback, but do care about argv and content.
    # The traceback is very bulky, so deleting it rather than comparing with
    # mock.ANY.
    for failure in error_dump[u'failures'].values():
      del failure[u'traceback']
    self.assertEqual(
        error_dump, {
            u'argv': sys.argv,
            u'version': mock.ANY,
            u'failures': {
                f.full_path: {
                    u'content': u'42'
                }
            }
        })

  def test_error_reading(self):
    f = self.create_tempfile(content='42')
    os.chmod(f.full_path, 0)  # remove access.
    with contextlib.redirect_stderr(six.StringIO()) as fake_stderr:
      self.main(['--mode=re', '42', '--sub=0', f.full_path])
    lines = fake_stderr.getvalue().splitlines()
    self.assertLen(lines, 1)
    self.assertStartsWith(lines[0], 'skipped %s: IOError: ' % f.full_path)

  def test_error_writing(self):
    f = self.create_tempfile(content='42')
    os.chmod(f.full_path, 0o444)  # Set to read-only.
    try:
      with contextlib.redirect_stderr(six.StringIO()) as fake_stderr:
        self.main(['--mode=re', '.*', '--sub=0', '-i', f.full_path])
    finally:
      os.chmod(f.full_path, 0o777)

    lines = fake_stderr.getvalue().splitlines()
    self.assertLen(lines, 1)
    self.assertStartsWith(lines[0], 'skipped %s: IOError: ' % f.full_path)

  def test_py_search(self):
    f = self.create_tempfile(content='x = foo()\n')

    output = self.main(
        ['--mode=py', 'ExprPattern("$f()")', '--no-filename', f.full_path])
    self.assertEqual(output, 'x = foo()\n')

  def test_py_skip_unparseable(self):
    f = self.create_tempfile(content='this is not python code')

    with contextlib.redirect_stderr(six.StringIO()) as fake_stderr:
      output = self.main(['--mode=py', '_', '--no-filename', f.full_path])
    self.assertEqual(output, '')
    self.assertRegex(
        fake_stderr.getvalue(), 'skipped %s: SyntaxError: .*' %
        os.path.join('.*', re.escape(os.path.basename(f.full_path))))

  def test_py_skip_nonutf8(self):
    f = self.create_tempfile(content=b'x = "\xff"')

    with contextlib.redirect_stderr(six.StringIO()) as fake_stderr:
      output = self.main(['--mode=py', '_', '--no-filename', f.full_path])
    self.assertEqual(output, '')
    self.assertRegex(
        fake_stderr.getvalue(), 'skipped %s: UnicodeDecodeError: .*' %
        os.path.join('.*', re.escape(os.path.basename(f.full_path))))

  def test_py_utf8_offsets(self):
    """Test that refex handles the byte / codepoint span conversion correctly.

    This test was inspired by b/128409342
    """
    temp_f = self.create_tempfile(content=u'"\xf1\xe9" + 123')

    # use sub-mode=sh to let invalid replacements still run so that we can
    # catch them in the assert.
    self.main([
        '--mode=py',
        'ExprPattern("123")',
        '--sub=x',
        temp_f.full_path,
        '-i',
        '--sub-mode=sh',
    ])
    self.assertEqual(temp_f.read_text(), u'"\xf1\xe9" + x')

  def test_py_handle_coding_declarations(self):
    for args in [['--mode=fix', '*', '-i'],
                 ['--mode=py.expr', 'a is 1', '--sub=a == 1', '-i']]:
      with self.subTest(args=args):
        f = self.create_tempfile(
            content='# coding: ascii\na is 1', file_path='temp.py')
        output = self.main(args + ['--no-filename', f.full_path])
        self.assertEqual(output, '-a is 1\n+a == 1\n')

  def test_py_search_color(self):
    f = self.create_tempfile(content='x = foo()\n')
    output = self.main([
        '--mode=py', 'ExprPattern("$f()", {"f": _})', '--no-filename',
        '--color=always', f.full_path
    ])
    self.assertRegex(output, r'x = .+foo.*\(\).+\n')

  def test_py_replace(self):
    f = self.create_tempfile(content='x = foo()\n')

    output = self.main([
        '--mode=py', 'ExprPattern("$f()")', '--sub=foo2()', '--no-filename',
        '-i', f.full_path
    ])
    self.assertEqual(output, '-x = foo()\n+x = foo2()\n')

  def test_py_replace_extra_variables(self):
    message = self.assert_main_error(
        ['--mode=py', '_', '--sub=$y+$z', os.devnull])
    self.assertEqual(
        message,
        'The substitution template(s) referenced variables not matched in the Python matcher: `y`, `z`'
    )

  def test_py_named_replace(self):
    f = self.create_tempfile(content='x = foo()\n')

    output = self.main([
        '--mode=py', 'ExprPattern("$f()")', '--sub=$f(2)', '--no-filename',
        '-i', f.full_path
    ])
    self.assertEqual(output, '-x = foo()\n+x = foo(2)\n')

  def test_py_named_replace_sh(self):
    f = self.create_tempfile(content='x = foo()\n')

    output = self.main([
        '--mode=py', 'ExprPattern("$f()")', '--sub=${f}2()', '--no-filename',
        '--sub-mode=sh', '-i', f.full_path
    ])
    self.assertEqual(output, '-x = foo()\n+x = foo2()\n')

  def test_py_named_replace_color(self):
    f = self.create_tempfile(content='x = foo()\n')

    unused_output = self.main([
        '--mode=py', 'ExprPattern("$f()")', '--sub=$f(2)', '--no-filename',
        '--color=always', '-i', f.full_path
    ])

  def test_py_replace_skip_rewriteerror(self):
    f = self.create_tempfile(content=u'[x]; x\n')
    self.main(['--mode=py', 'Name()', '--sub=', '-i', f.full_path])
    self.assertEqual(f.read_text(), '[x]; \n')

  def test_py_expr_search(self):
    """Also a quick test for the shortcut expression syntax."""
    f = self.create_tempfile(content='x = foo()\n')

    output = self.main(['--mode=py.expr', '$f()', '--no-filename', f.full_path])
    self.assertEqual(output, 'x = foo()\n')

  def test_py_stmt_search(self):
    """Also a quick test for the shortcut expression syntax."""
    f = self.create_tempfile(content='x = foo()\n')

    output = self.main(
        ['--mode=py.stmt', 'x = $f()', '--no-filename', f.full_path])
    self.assertEqual(output, 'x = foo()\n')

  def test_py_stmt_sub(self):
    f = self.create_tempfile(content='a = b\n')

    output = self.main(
        ['--mode=py.stmt', '$x = $y', '--sub', '$y = $x', '-i', f.full_path])
    self.assertEqual(f.read_text(), 'b = a\n')

  def test_py_ez_sub(self):
    """$f and $foo will be treated as separate variables."""
    for mode in ['py.expr', 'py.stmt']:
      with self.subTest(mode=mode):
        f = self.create_tempfile(content='1 + 2\n')

        output = self.main([
            '--mode=%s' % mode, '$f + $foo', '--sub=$f * $foo', '--no-filename',
            '-i', f.full_path
        ])
        # Note: not "1 * 1oo".
        self.assertEqual(output, '-1 + 2\n+1 * 2\n')

  def test_py_ez_sub_extra_variables(self):
    for mode in ['py.expr', 'py.stmt']:
      with self.subTest(mode=mode):
        message = self.assert_main_error(
            ['--mode=%s' % mode, '$x', '--sub=$y+$z', os.devnull])
        self.assertEqual(
            message,
            'The substitution template(s) referenced variables not matched in the Python matcher: `y`, `z`'
        )

  @parameterized.parameters(
      # Statement fragments can't be reparsed.
      'for a in foo: pass',
      'class C(foo): pass',
      'def x(): foo',
      # Expressions can need parenthesization.
      # note: this accidentally works fine if each line parses correctly
      # independently. For example, '(foo,\nbar)' works because it sees 'foo,'
      # and 'bar', two valid lines.
      # But '(foo\n,bar)' and '(foo,\n bar)' can't parse as two expressions,
      # only as one expression.
      '(foo,\n bar)')
  def test_py_ez_sub_bad_reparse(self, source):
    """Substitution works for suite statements and other parser edge cases."""
    f = self.create_tempfile(content=source)

    self.main([
        '--mode=py.expr', 'foo', '--sub=b', '--no-filename', '-i', f.full_path
    ])
    replaced = f.read_text()
    self.assertEqual(replaced, source.replace('foo', 'b'))

  def test_py_ez_sub_nobreak_syntax(self):
    for mode in ['py.expr', 'py.stmt']:
      with self.subTest(mode=mode):
        f = self.create_tempfile(content='self.assertTrue(1 == \n2)\n')

        output_safe = self.main([
            '--mode=%s' % mode, 'self.assertTrue($x)', '--sub=$x',
            '--no-filename', f.full_path
        ])
        output_unsafe = self.main([
            '--mode=%s' % mode, 'self.assertTrue($x)', '--sub=$x',
            '--sub-mode=sh', '--no-filename', f.full_path
        ])
        self.assertEqual(
            output_safe, '-self.assertTrue(1 == \n-2)\n+(1 == \n+2)\n'
            'This was a dry run. To write out changes, pass -i or --in-place.\n'
        )
        self.assertEqual(
            output_unsafe, '-self.assertTrue(1 == \n-2)\n+1 == \n+2\n'
            'This was a dry run. To write out changes, pass -i or --in-place.\n'
        )

  def test_py_ez_sub_nobreak_precedence(self):
    for mode in ['py.stmt']:
      with self.subTest(mode=mode):
        f = self.create_tempfile(content='x = 1, 2\n')

        output_safe = self.main([
            '--mode=py.stmt', 'x = $a', '--sub=x = foo($a)', '--no-filename',
            f.full_path
        ])
        output_unsafe = self.main([
            '--mode=py.stmt', 'x = $a', '--sub=x = foo($a)', '--sub-mode=sh',
            '--no-filename', f.full_path
        ])
        self.assertEqual(
            output_safe, '-x = 1, 2\n+x = foo((1, 2))\n'
            'This was a dry run. To write out changes, pass -i or --in-place.\n'
        )
        self.assertEqual(
            output_unsafe, '-x = 1, 2\n+x = foo(1, 2)\n'
            'This was a dry run. To write out changes, pass -i or --in-place.\n'
        )

  def test_py_ez_sub_nobreak_precedence_parent(self):
    """Python substitution results in the returned expression being a _subtree_.

    For example, replacing x with x + 1 will never result in a parse tree
    that doesn't have "x + 1" where "x" was -- e.g. if the original expression
    was x * 2, the new expression will be "(x + 1) * 2", not "x + 1 * 2".
    """
    f = self.create_tempfile(content='x * 2\n')
    output = self.main([
        '--mode=py.expr', 'x', '--sub=x+1', '--no-filename', f.full_path, '-i'
    ])
    self.assertEqual(output, '-x * 2\n+(x+1) * 2\n')

  def test_py_ez_sub_nobreak_precedence_list_parent(self):
    f = self.create_tempfile(content='[x]\n')
    output = self.main([
        '--mode=py.expr', 'x', '--sub=x, y', '--no-filename', f.full_path, '-i'
    ])
    self.assertEqual(output, '-[x]\n+[(x, y)]\n')

  @parameterized.parameters('[replaced]', '[x for x in replaced]')
  def test_py_ez_sub_nobreak_precedence_complex_parent(self, example):
    """Navigating one step up is often insufficient.

    For example: list comprehensions feature a comprehension() sub-node which
    is not syntactically valid by itself.

    Args:
      example: an expression containing the variable 'replaced'. The 'replaced'
        should occur in some part of the AST where there is a non-expr, non-stmt
        parent node, to verify that this is handled correctly.
    """
    f = self.create_tempfile(content=example)
    self.main([
        '--mode=py.expr', 'replaced', '--sub=replaced', '--no-filename',
        f.full_path, '-i'
    ])
    self.assertEqual(f.read_text(), example)

  def test_py_ez_sub_precedence_breaks_syntax(self):
    """Refex adds parens when it detects that missing parens breaks parsing.

    For example, many statements are delimited by commas -- and so are tuples.
    If there are the right number of commas in the tuple, it'll parse either
    way, but only the parenthesized version will have the correct syntax tree.
    If there are the wrong number of commas, it will fail to parse entirely
    without parenthesization. (Either way, parentheses must be added.)
    """
    f = self.create_tempfile(content='raise x\n')
    output = self.main([
        '--mode=py.expr', 'x', '--sub=1,2,3,4', '--no-filename', f.full_path,
        '-i'
    ])
    self.assertEqual(output, '-raise x\n+raise (1,2,3,4)\n')

  @parameterized.parameters(('--mode=py.expr', '--sub-mode=sh'),
                            ('--mode=re', '--sub-mode=py.expr'))
  def test_py_ez_sub_break_precedence_parent(self, mode, sub_mode):
    """Refex allows you to break precedence in unsafe substitution.

    In particular, if the substitution is not a Python substitution, or the
    match is not a Python match, you've signed your own death warrant.

    Args:
      mode: the --mode=... parameter.
      sub_mode: the --sub-mode=... parameter.
    """
    f = self.create_tempfile(content='x * 2\n')
    output_unsafe = self.main(
        [mode, sub_mode, 'x', '--sub=x+1', '--no-filename', f.full_path, '-i'])
    self.assertEqual(output_unsafe, '-x * 2\n+x+1 * 2\n')

  def test_py_ez_sub_precedence_differently_shaped_tree(self):
    f = self.create_tempfile(content='x(0)\n')
    output = self.main([
        '--mode=py.expr', 'x', '--sub=lambda x: x', '--no-filename',
        f.full_path, '-i'
    ])
    self.assertEqual(output, '-x(0)\n+(lambda x: x)(0)\n')

  def test_py_ez_sub_statements(self):
    # Don't try to apply to a whole statement in some indentation-unaware way...
    src = textwrap.dedent("""\
        if 1:
          if 2:
            pass
          else:
            pass
    """)
    f = self.create_tempfile(content=src)
    self.main(['--mode=py.expr', '2', '--sub=2 + x', f.full_path, '-i'])
    self.assertEqual(f.read_text(), src.replace('2', '2 + x'))

  def test_py_dict_search(self):
    """Dicts have a weird navigation order that could break serialization."""
    f = self.create_tempfile(content='{1:1,1:1}\n')

    self.main(
        ['--mode=py.expr', '1', '--sub=2', '--no-filename', f.full_path, '-i'])
    self.assertEqual(f.read_text(), '{2:2,2:2}\n')

  def test_py_regex(self):
    f = self.create_tempfile(content='deprecated_foo()\n')

    self.main([
        '--mode=py',
        r'MatchesRegex(r"deprecated_(?P<var>\w+)$")',
        '--sub=new_$var',
        '--sub-mode=sh',
        '--no-filename',
        f.full_path,
        '-i',
    ])
    self.assertEqual(f.read_text(), 'new_foo()\n')

  def test_fix_noop(self):
    hello_world = 'print("Hello, world!")'
    f = self.create_tempfile(content=hello_world, file_path='temp_test.py')
    output = self.main(['--mode=fix', '*', '--no-filename', f.full_path])
    self.assertEqual(output, '')
    self.assertEqual(f.read_text(), hello_world)  # unchanged

  def test_fix(self):
    f = self.create_tempfile(
        content='self.assertTrue(1 == 1)', file_path='temp_test.py')
    output = self.main(['--mode=fix', '*', '--no-filename', f.full_path])
    self.assertEqual(
        output, '-self.assertTrue(1 == 1)\n+self.assertEqual(1, 1)\n'
        'This was a dry run. To write out changes, pass -i or --in-place.\n')
    self.assertEqual(f.read_text(), 'self.assertTrue(1 == 1)')  # unchanged

  def test_fix_inplace(self):
    f = self.create_tempfile(
        content='self.assertTrue(1 == 1)', file_path='temp_test.py')
    output = self.main(['--mode=fix', '*', '--no-filename', f.full_path, '-i'])
    self.assertEqual(output,
                     '-self.assertTrue(1 == 1)\n+self.assertEqual(1, 1)\n')
    self.assertEqual(f.read_text(), 'self.assertEqual(1, 1)')

  def test_fix_twice(self):
    f = self.create_tempfile(
        content='(1 is 2)\n(3 is 4)', file_path='temp_test.py')
    # Using parens to force the ranges to be exactly correct: if some part
    # of the code doesn't use exactly the right range, we'll get parse errors,
    # because of unmatched parentheses.
    self.main(['--mode=fix', '*', '--no-filename', f.full_path, '-i'])
    self.assertEqual(f.read_text(), '(1 == 2)\n(3 == 4)')

  def test_fix_filename(self):
    f = self.create_tempfile(
        content='self.assertTrue(1 == 1)', file_path='not_a_python_file')
    output = self.main(['--mode=fix', '*', '--no-filename', f.full_path, '-i'])
    self.assertEqual(output, '')
    self.assertEqual(f.read_text(), 'self.assertTrue(1 == 1)')

    # devinj): Get sub --color working even without recent diff binary.
    # This is ridiculous!
    # self.assertRegexpMatches(output,
    # r'.+-x = foo\(\).+\n.+\+x = foo2\(\).+\n')


class FixTest(MainTestBase):
  """Testing suite for fixers."""

  # TODO: Move these to fixer_test.py?

  def assert_fixes(self,
                   initial,
                   after,
                   fixers='*',
                   file_suffix='.py',
                   extra_args=()):
    f = self.create_tempfile(content=initial, file_path='temp' + file_suffix)
    self.main(['--mode=fix', fixers, '--no-filename', f.full_path, '-i'] +
              list(extra_args))
    actual_after = f.read_text()
    self.assertEqual(actual_after, after)

  def test_is_eq(self):
    self.assert_fixes('a is 42', 'a == 42')
    self.assert_fixes('a is "xyz"', 'a == "xyz"')
    self.assert_fixes('a is u"xyz"', 'a == u"xyz"')
    self.assert_fixes('a is b"xyz"', 'a == b"xyz"')
    self.assert_fixes('a is r"xyz"', 'a == r"xyz"')

  def test_is_ne(self):
    self.assert_fixes('a is not 42', 'a != 42')
    self.assert_fixes('a is not "xyz"', 'a != "xyz"')
    self.assert_fixes('a is not u"xyz"', 'a != u"xyz"')
    self.assert_fixes('a is not b"xyz"', 'a != b"xyz"')
    self.assert_fixes('a is not r"xyz"', 'a != r"xyz"')

  @unittest.skipUnless(six.PY2, 'This parses python-2 only code. b/116355856')
  def test_long_literal(self):
    self.assert_fixes('0L', '0')
    self.assert_fixes('0l', '0')
    self.assert_fixes('-1L', '-1')
    really_big = str(sys.maxsize + 1)
    self.assert_fixes(really_big + 'L', really_big)

  def test_long_literal_nonmatches(self):
    """modern_python_fixers should not try to fix odd-looking non-longs."""
    self.assert_fixes('L', 'L')
    self.assert_fixes('v0L', 'v0L')
    self.assert_fixes('"0L"', '"0L"')
    self.assert_fixes('#0L', '#0L')

  @unittest.skipUnless(six.PY2, 'This parses python-2 only code. b/116355856')
  def test_octal_literal(self):
    self.assert_fixes('00', '0o0')  # definitely not an emoticon.
    self.assert_fixes('-03', '-0o3')  # still not an emoticon.

  def test_octal_literal_nonmatches(self):
    """modern_python fixers shouldn't touch the leading 0 in non-octals."""
    self.assert_fixes('0.3', '0.3')
    self.assert_fixes('000.3', '000.3')
    self.assert_fixes('01j', '01j')
    self.assert_fixes('0x0', '0x0')
    self.assert_fixes('0o0', '0o0')
    self.assert_fixes('0b0', '0b0')
    self.assert_fixes('"04"', '"04"')
    self.assert_fixes('#04', '#04')

  @unittest.skipUnless(six.PY2, 'This parses python-2 only code. b/116355856')
  def test_octal_long(self):
    self.assert_fixes('04L', '0o4')

  @unittest.skipUnless(six.PY2, 'This fixes python-2 only code. b/116355856')
  def test_basestring_six(self):
    self.assert_fixes('import six\n\nisinstance("", basestring)',
                      'import six\n\nisinstance("", six.string_types)')

  @unittest.skipUnless(six.PY2, 'This fixes python-2 only code. b/116355856')
  def test_basestring_nosix(self):
    """Without six, we can't rewrite basestring to six.string_types."""
    source = 'isinstance("", basestring)'
    self.assert_fixes(source, source)

  def test_assert_equal(self):
    self.assert_fixes('self.assertTrue(a == b)', 'self.assertEqual(a, b)')

  def test_fix_suppression_pylint(self):
    source = 'self.assertTrue(a == b)  # pylint: disable=g-generic-assert'
    self.assert_fixes(source, source)

  def test_fix_suppression_refex(self):
    source = 'self.assertTrue(a == b)  # refex: disable=pylint.g-generic-assert'
    self.assert_fixes(source, source)

  def test_fix_suppression_block(self):
    source = '# pylint: disable=g-generic-assert\nself.assertTrue(a == b)'
    self.assert_fixes(source, source)

  def test_fix_suppression_partial(self):
    source = ('# pylint: disable=g-generic-assert\n'
              'self.assertTrue(a == b)\n'
              '# pylint: enable=g-generic-assert\n'
              'self.assertTrue(a == b)\n')
    self.assert_fixes(source, ('# pylint: disable=g-generic-assert\n'
                               'self.assertTrue(a == b)\n'
                               '# pylint: enable=g-generic-assert\n'
                               'self.assertEqual(a, b)\n'))

  def test_fix_suppression_ignored(self):
    self.assert_fixes(
        'self.assertTrue(a == b)  # refex: disable=pylint.g-generic-assert',
        'self.assertEqual(a, b)  # refex: disable=pylint.g-generic-assert',
        extra_args=['--force-enable'])

  def test_assert_not_equal(self):
    self.assert_fixes('self.assertTrue(a != b)', 'self.assertNotEqual(a, b)')


#   def test_assert_is(self):
#     self.assert_fixes('self.assertTrue(a is b)', 'self.assertIs(a, b)')
#
#   def test_assertis_not(self):
#     self.assert_fixes('self.assertTrue(a is not b)', 'self.assertIsNot(a, b)')
#
#   def test_assert_not_is(self):
#     self.assert_fixes('self.assertTrue(not a is b)', 'self.assertIsNot(a, b)')

  def test_assert_in(self):
    self.assert_fixes('self.assertTrue(a in b)', 'self.assertIn(a, b)')

  def test_assert_not_in(self):
    self.assert_fixes('self.assertTrue(a not in b)', 'self.assertNotIn(a, b)')

  def test_assert_not_in_prefix(self):
    self.assert_fixes('self.assertTrue(not a in b)', 'self.assertNotIn(a, b)')

  def test_assert_gt(self):
    self.assert_fixes('self.assertTrue(a > b)', 'self.assertGreater(a, b)')

  def test_assert_ge(self):
    self.assert_fixes('self.assertTrue(a >= b)',
                      'self.assertGreaterEqual(a, b)')

  def test_assert_lt(self):
    self.assert_fixes('self.assertTrue(a < b)', 'self.assertLess(a, b)')

  def test_assert_le(self):
    self.assert_fixes('self.assertTrue(a <= b)', 'self.assertLessEqual(a, b)')

  def test_assert_isinstance(self):
    self.assert_fixes('self.assertTrue(isinstance(a, b))',
                      'self.assertIsInstance(a, b)')

  def test_assert_not_isinstance(self):
    self.assert_fixes('self.assertTrue(not isinstance(a, b))',
                      'self.assertNotIsInstance(a, b)')

  def test_assert_not_isinstance_assertfalse(self):
    self.assert_fixes('self.assertFalse(isinstance(a, b))',
                      'self.assertNotIsInstance(a, b)')

  def test_assert_isinstance_assertfalse(self):
    self.assert_fixes('self.assertFalse(not isinstance(a, b))',
                      'self.assertIsInstance(a, b)')

  def test_assert_multirewrite(self):
    # "assert_(a is None)" -> "assertTrue(a is None)" -> "assertIs(a, None)"
    self.assert_fixes('self.assert_(a is None)', 'self.assertIs(a, None)')

  def test_attrib_mutable_default(self):
    self.assert_fixes('attr.ib(default=[])', 'attr.ib(factory=list)')

if __name__ == '__main__':
  absltest.main()
