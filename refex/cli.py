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
"""
:mod:`refex.cli`
================

Command-line interface to Refex, and extension points to that interface.

This module allows you to define your own ``main()`` function by calling
:func:`run_cli` with alternative arguments, which is a blunt and silly extension
point to allow for users to extend the refex CLI with new features.

"""
from __future__ import absolute_import
from __future__ import division
# from __future__ import google_type_annotations
from __future__ import print_function

import argparse
import atexit
import collections
import contextlib
import cProfile as profile
import errno
import io
import json
import os
import re
import sys
import tempfile
import textwrap
import traceback
from typing import Dict, Iterable, List, Optional, Text, Tuple, Union

from absl import app
import attr
import colorama
import pkg_resources
import six

from refex import formatting
from refex import search
from refex.fix import find_fixer
from refex.python import syntactic_template

_IGNORABLE_ERRNO = frozenset([
    errno.ENOENT,  # file was removed after we went looking
    errno.EISDIR,  # ^, plus then a directory was put there.
])


def _shorten_path(path):
  filenames = [path, os.path.abspath(path), os.path.relpath(path)]
  return min(filenames, key=len)


# The number of times to iterate a search-replace, if no explicit count is
# given but iteration is to done.
_DEFAULT_ITERATION_COUNT = 10


@attr.s
class RefexRunner(object):
  """The application logic of the refex CLI app.

  This implementation should work for a normal unix-y filesystem. Subclasses can
  override methods to handle more exotic filesystems as needed.

  All methods in this class and subclasses should be thread safe, since they may
  be executed in a multithreaded context from within the same instance of the
  class.
  NOTE: currently log_changes isn't thread safe, that should be fixed or
  updated.

  Subclasses should consider overriding the following methods:
    * ``__init__()``
    * :meth:`read()`
    * :meth:`rewrite_files()`

  It may be necessary to override :meth:`get_matches()`, but this seems
  unlikely.
  """
  searcher = attr.ib()
  renderer = attr.ib(factory=formatting.Renderer)
  dry_run = attr.ib(default=True)
  show_diff = attr.ib(default=True)
  show_files = attr.ib(default=True)
  verbose = attr.ib(default=False)
  max_iterations = attr.ib(default=_DEFAULT_ITERATION_COUNT)

  def read(self, path: str) -> Optional[Text]:
    """Reads in a file and return the resulting content as unicode.

    Since this is only called from the loop within :meth:`rewrite_files`,
    non-fatal failures should return ``None``.

    Args:
      path: The path to the file.

    Returns:
      An optional unicode string of the file content.
    """
    try:
      with io.open(path, 'r', encoding='utf-8') as d:
        return d.read()
    except UnicodeDecodeError as e:
      print('skipped %s: UnicodeDecodeError: %s' % (path, e), file=sys.stderr)
      return None
    except IOError as e:
      if e.errno not in _IGNORABLE_ERRNO:
        print('skipped %s: IOError: %s' % (path, e.strerror), file=sys.stderr)
      return None

  def get_matches(self, contents, path):
    """Finds all refex matches in the file.

    Args:
      contents: File contents to analyze.
      path: The path to the above content.

    Returns:
      A list of refex Match objects.
    """
    try:
      return list(
          search.find_iter(
              self.searcher, contents, path,
              max_iterations=self.max_iterations))
    except search.SkipFileNoResultsError:
      return []
    except search.SkipFileError as e:
      print('skipped %s: %s' % (path, e), file=sys.stderr)
      return []

  def write(self, path, content, matches):
    if not self.dry_run:
      try:
        with io.open(path, 'w', encoding='utf-8') as f:
          f.write(formatting.apply_substitutions(content, matches))
      except IOError as e:
        print('skipped %s: IOError: %s' % (path, e), file=sys.stderr)

  # TODO(b/131232240): Make this thread safe.
  def log_changes(self, content, matches, name, renderer):
    """Prints any changes, depending on the config."""
    # It's probably worth rewriting this so that it yields strings of the
    # partial diffs instead of a bool?
    if not matches:
      return False
    if not self.show_diff and not self.show_files:
      return False
    if not self.show_diff and self.show_files:
      print(name)
      return False

    if self.show_files:
      print(('{colorama.Style.RESET_ALL}{colorama.Fore.MAGENTA}'
             '{filename}'
             '{colorama.Style.RESET_ALL}'.format(
                 colorama=colorama, filename=name)))
    has_any_changes = False
    for has_changes, part in formatting.diff_substitutions(
        content, matches, name, renderer):
      has_any_changes = has_any_changes or has_changes
      if part:
        sys.stdout.write(part)
        sys.stdout.flush()
    return has_changes

  def rewrite_files(self, path_pairs):
    """Main access point for rewriting.

    Args:
      path_pairs: A list of ``(read, write)`` filenames. For most users, if the
        list of files is ``files``, ``rewrite_files(zip(files, files))`` should
        work.

    Returns:
      A JSON-serializable dict of filename to failure information. Only files
      that failed to load are in this dict.
    """
    failures = {}
    has_changes = False
    for read, write in path_pairs:
      display_name = _shorten_path(write)
      content = self.read(read)
      if content is not None:
        try:
          matches = self.get_matches(content, display_name)
        except Exception as e:  # pylint: disable=broad-except
          failures[read] = {
              'content': content,
              'traceback': traceback.format_exc()
          }
          print(
              'skipped {path}: {e.__class__.__name__}: {e}'.format(
                  path=read, e=e),
              file=sys.stderr)
        else:
          has_changes |= (
              self.log_changes(content, matches, display_name, self.renderer))
          self.write(write, content, matches)
    if has_changes and self.dry_run:
      # If there were changes that the user might have wanted to apply, but they
      # were in dry run mode, print a note for them.
      print('This was a dry run. To write out changes, pass -i or --in-place.')
    return failures


_BUG_REPORT_URL = 'https://github.com/ssbr/refex/issues/new/choose'


# It was at this point, dear reader, that this programmer wondered if using
# argparse was a mistake after all.
#
# The following classes implement most of the support for specifying patterns
# and replacement templates on the command line.


@attr.s
class _SearchReplaceArgument(object):
  """A --match/--sub pair."""
  #: The pattern.
  match = attr.ib(default=None, type=str)
  #: The replacement (specified via --sub or --named-sub)
  sub = attr.ib(default=None, type=Optional[Dict[str, str]])


def _setdefault_searchreplace(o, name):
  value = getattr(o, name, None)
  if value is None:
    value = [_SearchReplaceArgument()]
    setattr(o, name, value)
  return value


class _AddMatchAction(argparse.Action):

  def __init__(self, option_strings, dest, nargs=None, **kwargs):
    if nargs is not None:
      raise ValueError('nargs not allowed')
    super(_AddMatchAction, self).__init__(option_strings, dest, **kwargs)

  def __call__(self, parser, namespace, value, option_string=None):
    search_replaces = _setdefault_searchreplace(namespace, self.dest)
    if search_replaces[-1].match is not None:
      search_replaces.append(_SearchReplaceArgument())
    search_replaces[-1].match = value


class _AddSubAction(argparse.Action):

  def __init__(self, option_strings, dest, nargs=None, **kwargs):
    if nargs is not None:
      raise ValueError('nargs not allowed')
    super(_AddSubAction, self).__init__(option_strings, dest, **kwargs)

  def __call__(self, parser, namespace, value, option_string=None):
    search_replaces = _setdefault_searchreplace(namespace, self.dest)
    old_sub = search_replaces[-1].sub
    if old_sub is not None:
      parser.error(
          'The most recent --match pattern has already had a substitution defined (tried to overwrite %s with --sub %s)'
          % (old_sub, value))

    search_replaces[-1].sub = {search.ROOT_LABEL: value}


class _AddNamedSubAction(argparse.Action):

  def __init__(self, option_strings, dest, nargs=None, **kwargs):
    if nargs is not None:
      raise ValueError('nargs not allowed')
    super(_AddNamedSubAction, self).__init__(option_strings, dest, **kwargs)

  def __call__(self, parser, namespace, value, option_string=None):
    search_replaces = _setdefault_searchreplace(namespace, self.dest)
    old_sub = search_replaces[-1].sub
    if old_sub is None:
      old_sub = search_replaces[-1].sub = {}
    if search.ROOT_LABEL in old_sub:
      parser.error(
          "Can't combine --sub and --named-sub (tried to merge --sub {} and --named-sub {}".format(old_sub[search.ROOT_LABEL], value))

    name, sep, pattern = value.partition('=')
    if not sep:
      parser.error(
          '--named-sub incorrectly specified, missing "=": {}'.format(value))
    if name in old_sub:
      parser.error(
          '--named-sub specified twice for the same key: {}, {}'.format(old_sub[name], pattern))
    old_sub[name] = pattern


def _absl_run_separate_argv(main_func, main_argv, absl_argv):
  """Runs main via absl.app.run(), passing different argv to main and to absl.

  Args:
    main_func: A function main(main_argv).
    main_argv: The argv to pass to main.
    absl_argv: The argv to pass to absl.
  """

  def absl_main(unused_argv):
    return main_func(main_argv)

  app.run(absl_main, argv=absl_argv)


def run(runner: RefexRunner,
        files: Iterable[Union[str, Tuple[str, str]]],
        bug_report_url: Text,
        version: Text = '<unspecified>'):
  """Performs console setup, and runs.

  Args:
    runner: a :class:`RefexRunner`.
    files: the list of files to rewrite using `runner`. If the output file is
      different from the input file, a pair ``(input, output)`` may be passed
      instead of just ``inout``.
    bug_report_url: if a failure occurs, the URL to report bugs to.
    version: The version to write to debug logs.
  """
  files = (
      (fname, fname) if isinstance(fname, str) else fname for fname in files)
  try:
    with _report_bug_excepthook(bug_report_url):
      with colorama.colorama_text(strip=not runner.renderer.color):
        report_failures(
            runner.rewrite_files(files),
            bug_report_url,
            version,
            runner.verbose,
        )
  except KeyboardInterrupt:
    pass


def run_cli(argv,
            parser,
            get_runner,
            get_files,
            bug_report_url=_BUG_REPORT_URL,
            version='<unspecified>'):
  """Creates a runner from command-line arguments, and executes it.

  Args:
    argv: argv
    parser: An ArgumentParser.
    get_runner: called with (parser, options)
      returns the runner to use.
    get_files: called with (runner, options)
      returns the files to examine, as [(in_file, out_file), ...] pairs.
    bug_report_url: An URL to present to the user to report bugs.
        As the error dump includes source code, corporate organizations may
        wish to override this with an internal bug report link for triage.
    version: The version number to use in bug report logs and --version
  """
  with _report_bug_excepthook(bug_report_url):
    _add_rewriter_arguments(parser)

    # For legacy reasons, refex uses argparse. This isn't very easily
    # compatible with using app.run() -- what if someone defines a flag that
    # conflicts with an argparse flag?
    # Nonetheless, we want to use app.run to allow interop with absl-using
    # libraries. So we process argparse flags first, and then give app.run() a
    # fake argv of zilch.
    #
    # In the future, one could imagine providing a --absl-flag= option in
    # argparse to let one override absl-flag values, but for now let's just
    # ignore it.

    def main_for_absl(argv):
      options = _parse_options(argv[1:], parser)
      runner = get_runner(parser, options)
      files = get_files(runner, options)

      def _run():
        """A wrapper function for profiler.runcall."""
        run(runner, files, bug_report_url, version)

      if options.profile_to:
        profiler = profile.Profile()
        atexit.register(profiler.dump_stats, options.profile_to)
        profiler.runcall(_run)
      else:
        _run()

    try:
      _absl_run_separate_argv(main_for_absl, argv, [argv[0]])
    except KeyboardInterrupt:
      pass


def report_failures(failures, bug_report_url, version, verbose):
  """Reports :meth:`RefexRunner.rewrite_files` failures, if any.

  These are written to a debug log file (readable via the developer script
  :command:`rxerr_debug`), and to stderr.

  Args:
    failures: The return value of :meth:`RefexRunner.rewrite_files`.
    bug_report_url: An URL to present to the user to report bugs.
    version: The version number to write to debug logs.
    verbose: If true, writes failures to stderr in addition to debug logs.
  """
  if not failures:
    return

  if verbose:
    for fname, failure in failures.items():
      print('Error processing', fname, file=sys.stderr)
      print(failure['traceback'], file=sys.stderr)
      print('', file=sys.stderr)

  error_blob = dict(failures=failures, argv=sys.argv, version=version)
  if six.PY2:
    kw = {'mode': 'wb'}  # ok because of ensure_ascii=True below.
  else:
    kw = {'mode': 'w', 'encoding': 'utf-8'}
  with tempfile.NamedTemporaryFile(
      prefix='rxerr_', suffix='.json', delete=False, **kw) as f:
    json.dump(error_blob, f, ensure_ascii=True)

  print(
      'Encountered {n} error(s). Report bugs to {bug_link}, and attach {f.name}'
      .format(n=len(failures), bug_link=bug_report_url, f=f),
      file=sys.stderr)
  print(
      'NOTE: the error dump file above contains reproduction instructions,'
      ' including source code and program arguments.',
      file=sys.stderr)


def _fixer_from_pattern(pattern, templates):
  # templates is null unless you pass in a --sub argument,
  # which doesn't make sense for this search mode.
  if templates is not None:
    raise ValueError(
        'Cannot override substitution (--sub, --named-sub) with --mode=fix')
  return find_fixer.from_pattern(pattern)


_SEARCH_MODES = collections.OrderedDict([
    ('re', search.RegexSearcher.from_pattern),
    ('py', search.PyMatcherRewritingSearcher.from_pattern),
    ('py.expr', search.PyExprRewritingSearcher.from_pattern),
    ('py.stmt', search.PyStmtRewritingSearcher.from_pattern),
    ('fix', _fixer_from_pattern),
])

_SUB_MODES = collections.OrderedDict([
    ('re', formatting.RegexTemplate),
    ('sh', formatting.ShTemplate),
    ('py', syntactic_template.PythonTemplate),
    ('py.expr', syntactic_template.PythonExprTemplate),
    ('py.stmt', syntactic_template.PythonStmtTemplate),
])

_DEFAULT_SUB_MODES = {
    're': 're',
    'py': 'py',
    'py.expr': 'py.expr',
    'py.stmt': 'py.stmt',
    'fix': None,  # unused / not a dict-based searcher.
}

_NONZERO_ITERATION_MODES = frozenset({'fix'})

assert set(_DEFAULT_SUB_MODES) == set(_SEARCH_MODES)

_color_choices = collections.OrderedDict([
    ('never', False),
    ('always', True),
    ('auto', sys.stdout.isatty()),
])


@contextlib.contextmanager
def _report_bug_excepthook(bug_report_url):
  """Patches sys.excepthook to add a bug report link."""

  def hook(*args, **kwargs):
    sys.__excepthook__(*args, **kwargs)
    print('Is this a bug? Report it to %s' % bug_report_url, file=sys.stderr)

  old_hook = sys.excepthook
  sys.excepthook = hook

  try:
    yield
  finally:
    sys.excepthook = old_hook


def _get_sub_parser(options):
  sub_mode = options.sub_mode
  if sub_mode == 'auto':
    sub_mode = _DEFAULT_SUB_MODES[options.mode]
  if sub_mode is None:
    # This mode doesn't support --sub/etc. args, will fail later
    # For now, default to sh templates.
    sub_mode = 'sh'
  return _SUB_MODES[sub_mode]


def _parse_templates(parser, sub_parser, templates):
  """Parses the template mapping from args."""
  if templates is None:
    return None

  for name, sub in templates.items():
    try:
      template = sub_parser(sub)
    except Exception as e:  # Don't want to hardcode which exceptions each template can raise: pylint: disable=broad-except
      parser.error(str(e))  # exits

    templates[name] = template
  return templates


def _add_rewriter_arguments(parser):
  """Adds common arguments to an already-defined parser.

  These control the behavior of the search.

  Args:
    parser: An argparse.ArgumentParser.
  """
  grep_options = parser.add_argument_group(
      'search settings',
      'Arguments for use when performing search without replacement.')
  debug_options = parser.add_argument_group('debug settings')

  parser.add_argument(
      '--recursive',
      '-R',
      action='store_true',
      help='Expand passed file paths recursively.')
  parser.add_argument('--norecursive', action='store_false', dest='recursive')

  parser.add_argument('--excludefile',
                      type=re.compile,
                      metavar='REGEX',
                      help='Filenames to exclude (regular expression).')
  parser.add_argument('--includefile',
                      type=re.compile,
                      metavar='REGEX',
                      help='Filenames that must match to include'
                      ' (regular expression).')
  parser.add_argument(
      '--also',
      type=search.default_compile_regex,
      metavar='REGEX',
      action='append',
      default=[],
      help='Regexes that must also match somewhere in the file.')
  parser.add_argument(
      '--noalso',
      type=search.default_compile_regex,
      metavar='REGEX',
      action='append',
      default=[],
      help='Regexes that must match nowhere in the file.')
  parser.add_argument(
      '--color',
      help='Whether to color the output.',
      choices=tuple(_color_choices))
  parser.add_argument(
      '--nocolor',
      help='Disable output color. (DEPRECATED)',
      action='store_const',
      dest='color',
      const='never')
  grep_options.add_argument(
      '--force-enable',
      action='store_true',
      default=False,
      help='Ignore pragmas that disable substitutions.')
  grep_options.add_argument('-l',
                            action='store_true',
                            default=False,
                            dest='list_files',
                            help='Only print out file names, if grepping.')
  grep_options.add_argument(
      '--format',
      type=six.text_type,
      default='{head}{match}{tail}',
      help='Format to display matches in. Variables available:'
      ' head, tail, match, path',
      metavar='FORMAT')
  grep_options.add_argument(
      '-o',
      '--only-matching',
      action='store_const',
      const='{match}',
      dest='format',
      help='Only print match. Equivalent to --format="{match}".')
  grep_options.add_argument(
      '--no-filename',  # grep also uses -h, but that's stupid.
      action='store_false',
      dest='print_filename',
      help='Suppress the filename in output. (Opposite of --with-filename)')
  grep_options.add_argument(
      '--with-filename',  # grep also uses -H, but that's... well, whatever.
      action='store_true',
      dest='print_filename',
      help='Print the filename in output'
      ' (true by default, but disabled by --no-filename).',)
  dry_run_arguments = parser.add_mutually_exclusive_group()
  dry_run_arguments.add_argument(
      '--dry-run',
      action='store_const',
      const=False,
      dest='in_place',
      help="Don't write anything to disk. (The default)")
  dry_run_arguments.add_argument('--in-place',
                                 '-i',
                                 action='store_const',
                                 const=True,
                                 dest='in_place',
                                 help='Write changes back to disk.')

  debug_options.add_argument(
      '--profile-to',
      metavar='FILE',
      help='Profile main() and write results to disk at FILE.')
  debug_options.add_argument(
      '-v',
      '--verbose',
      action='store_const',
      const=True,
      default=False,
      help='Log intermediate actions.')

  parser.set_defaults(
      in_place=False,
      print_filename=True,
      color='auto',
      diff=False,
      recursive=False,
  )


def _parse_args_leftovers(parser, args):
  """Parse arguments as if all leftovers were an nargs=* positional argument.

  This is similar to parse_known_args, but it treats arguments beginning with
  '-' as unknown flags, unless it encounters a '--' first.

  Unfortunately, without this trick, argparse requires all positional arguments
  be in one contiguous block, which is not consistent with other command line
  programs and not especially intuitive. This is one argument in favor of using
  click instead.

  Args:
    parser: An ArgumentParser.
    args: The args to pass to parser.parse_known_args.

  Returns:
    options, leftovers
  """
  options, unknown = parser.parse_known_args(args)
  leftovers = []
  unknown_it = iter(unknown)
  unrecognized_flags = []
  # first loop: things that look like flags are treated as unrecognized flags.
  for arg in unknown_it:
    if arg == '--':
      break
    elif arg.startswith('-'):
      unrecognized_flags.append(arg)
    else:
      leftovers.append(arg)
  # second loop: if there are any args left in the iterator, it's because of a
  # --, which escapes all later arguments.
  leftovers.extend(unknown_it)

  if unrecognized_flags:
    parser.error('unrecognized arguments: %s' % ' '.join(unrecognized_flags))

  return options, leftovers


def _parse_options(argv, parser):
  """Parses arguments using :mod:`argparse`, and returns the options object.

  Args:
    argv: ``sys.argv[1:]``
    parser: An :class:`argparse.ArgumentParser`.

  Returns:
    The parsed options.
  """
  options, args = _parse_args_leftovers(parser, argv)
  options.files = []
  if options.pattern_or_file is not None:
    if (len(options.search_replace) == 1
        and options.search_replace[0].match is None):
      options.search_replace[0].match = options.pattern_or_file
    else:
      options.files.append(options.pattern_or_file)
  options.files.extend(args)
  options.color = _color_choices[options.color]
  options.renderer = formatting.Renderer(
      match_format=options.format,
      color=options.color,
  )

  return options


def argument_parser(version):
  """Creates an :class:`argparse.ArgumentParser` for the refex CLI."""
  if six.PY2:
    extra_kwargs = {}
  else:
    extra_kwargs = {'allow_abbrev': False}
  parser = argparse.ArgumentParser(
      formatter_class=argparse.RawDescriptionHelpFormatter,
      description=textwrap.dedent("""\
          Syntactically aware search/replace."""),
      epilog=textwrap.dedent("""\
          ===

          Example usage (--mode=re):
            %(prog)s --mode=re "TOOD\\(($USER)\\):" --sub "TODO:" -R . -i
                Replace your TOODs with TODO.
            %(prog)s --mode=re "gordon freeman" -R .
                Find instances of "gordon freeman".
            %(prog)s --mode=re "gordon freeman must die" -l -R . | xargs $EDITOR
                Edit all files containing "gordon freeman must die"
          ===

          Example usage (--mode=py.expr):
            %(prog)s --mode=py.expr 'set($x for $x in $y)' --sub='{{$x for $x in y}}' -R . -i
                Replace old-style set creation with set comprehensions.
          """),
      **extra_kwargs)

  parser.add_argument('--version', action='version', version=version)

  match_options = parser.add_argument_group(
      'match arguments',
      'Arguments for use when performing search-replace (when passing the '
      'REPLACEMENT argument).')

  match_options.add_argument(
      '--mode',
      choices=sorted(_SEARCH_MODES),
      required=True,
      help='Pattern matching mode')

  match_options.add_argument(
      'pattern_or_file',
      type=six.text_type,
      metavar='PATTERN_OR_FILE',
      nargs='?',
      default=None,
      help='Implicit --match argument, only used if --match is not.',
  )

  search_replace_dest = 'search_replace'

  match_options.add_argument(
      '--match',
      type=six.text_type,
      action=_AddMatchAction,
      help='Pattern expression.',
      metavar='PATTERN',
      dest=search_replace_dest,
  )

  match_options.add_argument(
      '--sub',
      type=six.text_type,
      action=_AddSubAction,
      help='Replacement expression, making this search-replace.',
      metavar='REPLACEMENT',
      dest=search_replace_dest,
  )
  # TODO: Make this work with regular expressions.
  match_options.add_argument(
      '--named-sub',
      type=six.text_type,
      action=_AddNamedSubAction,
      help=('Replacement expression to use for a specific '
            'bound name. Format is name=replacement.'),
      dest=search_replace_dest,
  )

  match_options.add_argument(
      '--sub-mode',
      choices=['auto'] + list(_SUB_MODES),
      default='auto',
      help=(r'Substitution syntax type e.g. \g<foo> (re) vs $foo (sh).'
            ' Defaults to re for --mode=re, sh for all other modes.'))

  match_options.add_argument(
      '--iterate',
      default=None,
      const=_DEFAULT_ITERATION_COUNT,
      nargs='?',
      type=int,
      metavar='N',
      help=('Whether to re-apply the search-replace to attempt to merge fixes.'
            ' If no number N is provided, defaults to {n}. If not provided,'
            ' then it defaults to 0 for user-specified search/replace, and {n}'
            ' for built-in iteration-compatible search/replace (i.e. fix).'
            .format(n=_DEFAULT_ITERATION_COUNT)),
  )

  match_options.add_argument(
      '--no-iterate',
      action='store_const',
      dest='iterate',
      const=None,
  )

  parser.set_defaults(
      rewriter=None,
      **{search_replace_dest: [_SearchReplaceArgument()]}
  )

  return parser


def runner_from_options(parser, options) -> RefexRunner:
  """Returns a runner based on CLI flags."""

  searchers = []
  sub_parser = _get_sub_parser(options)
  searcher_factory = _SEARCH_MODES[options.mode]
  for sr in options.search_replace:
    pattern = sr.match
    templates = _parse_templates(parser, sub_parser, sr.sub)
    try:
      searchers.append(searcher_factory(pattern, templates))
    except ValueError as e:
      parser.error(str(e))

  if len(searchers) == 0:
    raise AssertionError("Bug in refex: there should always be a (possibly empty) search-replace pair.")
  elif len(searchers) == 1:
    [searcher] = searchers
  else:
    searcher = search.CombinedSearcher(searchers)

  if options.also or options.noalso:
    searcher = search.AlsoRegexpSearcher(
        searcher=searcher, also=options.also, also_not=options.noalso)

  if not options.force_enable:
    searcher = search.PragmaSuppressedSearcher(searcher)

  iteration_count = options.iterate
  if iteration_count is None:
    if options.mode in _NONZERO_ITERATION_MODES:
      iteration_count = _DEFAULT_ITERATION_COUNT
    else:
      iteration_count = 0

  return RefexRunner(
      searcher=searcher,
      renderer=options.renderer,
      dry_run=not options.in_place,
      show_diff=not options.list_files,
      show_files=options.list_files or options.print_filename,
      verbose=options.verbose,
      max_iterations=iteration_count,
  )


def files_from_options(runner, options) -> List[Tuple[str, str]]:
  """Returns the list of files specified by the command line options."""
  del runner
  return list(zip(options.files, options.files))


def main(argv=None, bug_report_url=_BUG_REPORT_URL, version=None):
  """The refex main function."""
  if argv is None:
    argv = sys.argv
  if version is None:
    try:
      version = pkg_resources.get_distribution('refex').version
    except pkg_resources.DistributionNotFound as e:
      # e.g. if vendored *cough* :(
      version = 'DistributionNotFound: {e}\n{long_desc}'.format(
          e=e,
          long_desc='(refex needs to be installed to have version information)',
      )
  parser = argument_parser(version=version)
  run_cli(
      argv,
      argument_parser(version=version),
      runner_from_options,
      files_from_options,
      bug_report_url=bug_report_url,
      version=version,
  )
