# Refex - refactoring expressions

Refex is a syntactically aware search-and-replace tool for Python, which allows you to specify code searches and rewrites using templates, or a
more complex
[Clang-LibASTMatcher](https://clang.llvm.org/docs/LibASTMatchersTutorial.html#intermezzo-learn-ast-matcher-basics)-like
matcher interface.

## Examples

**Automatic parenthesis insertion:** Refex will automatically insert parentheses
to preserve the intended code structure:

```sh
$ echo "a = b.foo() * c" > test.py
$ refex --mode=py.expr '$x.foo()' --sub='$x.foo() + 1' -i test.py
...
$ cat test.py
a = (b.foo() + 1) * c
```

A naive regular expression replacement would have resulted in `b.foo() + 1 * c`, which is not
equivalent, and is unrelated to the intended replacement.

**Paired parentheses:** Refex is aware of the full syntax tree, and will always match parentheses correctly:

```sh
$ echo "print(foo(bar(b))" > test.py
$ refex --mode=py.expr 'foo($x)' --sub='foo($x + 1)' -i test.py
...
$ cat test.py
a = print(foo(bar(b) + 1))
```

Here, a naive replacement using regular expressions could have resulted in
either `print(foo(bar(b)) + 1)` or `print(foo(bar(b) + 1))`, depending on
whether `$x` was matched greedily or non-greedily.

**Combining replacements:** you can pass multiple search/replace pairs to
Refex which combine to do more complex rewrites. For example:

```sh
# Rewrites "self.assertTrue(x == False)" to "self.assertFalse(x)", even though
# that was not explicitly called out.
refex --mode=py.expr -i --iterate \
  --match='self.assertTrue($x == $y)'  --sub='self.assertEqual($x, $y)' \
  --match='self.assertEqual($x, False)' --sub='self.assertFalse($x)' \
  -R dir/
```

TODO: also describe `--mode=py`.

## Getting started

### Installation

TODO: Installation instructions will go here as soon as this gets up on PyPI,
hang tight!

## Current status

NOTE: Right now, the project is in the process of initial upload to github,
PyPI, etc., so please don't publicize it widely. The initial release will be
a `0.1` release.

**Stable:**

The APIs documented at https://refex.readthedocs.io/ are expected to remain
mostly the same, except for trivial renames and moves.

These command-line interfaces are expected to remain roughly the same, without
backwards-incompatible changes:

* `--mode=py.expr`
* `--mode=fix`
* `--mode=re`

**Unstable**

* All undocumented APIs (*especially* the API for creating a new matcher).
* `--mode=py.stmt` is missing many safety and convenience features.
* `--mode=py`, the matcher interface, will eventually need some fairly large
  restructuring to make it O(n), although simple uses should be unaffected.

(Also, all the stable parts are unstable too. This isn't a promise, just an
expectation/statement of intent.)

## Contributing

See the
[contribution guide](https://refex.readthedocs.io/en/latest/meta/contributing.html)

## See Also

*   [asttokens](https://github.com/gristlabs/asttokens): the token-preserving
    AST library that Refex is built on top of.
*   [Pasta](https://github.com/google/pasta): a code rewriting tool using AST
    mutation instead of string templates.
*   [Semgrep](https://github.com/returntocorp/semgrep): cross-language AST
    search using a similar approach.
*   [lib2to3](https://docs.python.org/3/library/2to3.html#module-lib2to3): the
    standard library's code rewriting tool based on the concrete syntax tree.

## Disclaimer

You may have noticed Google copyright notices. This is not an officially
supported Google product.
