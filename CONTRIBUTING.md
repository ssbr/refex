# How to Contribute

## Community Guidelines

This project follows
[Google's Open Source Community Guidelines](https://opensource.google/conduct/).

## Changing Refex

TODO: more explanation than just this.

TODO: configuration for linter, yapf, isort (pending issue
[#1486](https://github.com/PyCQA/isort/issues/1486)), pre-commit hooks (?), and
CI/github actions.

To run the tests:

```sh
$ pipx run tox -e py38
```

Due to the use of the [absltest](https://abseil.io/docs/python/guides/testing)
framework, Refex cannot use many test runners. See
[conftest.py](https://github.com/ssbr/refex/blob/master/refex/conftest.py).

## Code Review

Finally, send a pull request!

All submissions, including submissions by project members, require code review.
See [GitHub Help](https://help.github.com/articles/about-pull-requests/) for
information on how to make a pull request.

### Contributor License Agreement

Contributions to this project must be accompanied by a Contributor License
Agreement (CLA). You (or your employer) retain the copyright to your
contribution; this simply gives us permission to use and redistribute your
contributions as part of the project. Head over to
https://cla.developers.google.com/ to see your current agreements on file or
to sign a new one.

You generally only need to submit a CLA once, so if you've already submitted one
(even if it was for a different project), you probably don't need to do it
again.


## Why is the source code so weird?

### Two Space Indents

Refex uses two space indents because it originated in
[Google](https://google.github.io/styleguide/pyguide.html). You get used to it.
In fact, because indents are 2 spaces, and hanging indents are 4 spaces, it's
much easier in Google-style Python than most code to distinguish between nested
code inside of a function, vs e.g. function parameters that went on many lines.

### Python 2 Half-Support

A lot of code in Refex appears to support Python 2, but if you try it, Refex
quite obviously does not work on Python 2 -- or rather, it doesn't without a
patch to support Python 3 annotation syntax. That patch is available from
[pytype](https://github.com/google/pytype/blob/master/2.7_patches/python_2_7_type_annotations.diff).

Refex won't even support that much after Dec 2020.
