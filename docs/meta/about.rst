About Refex
===========

Goals
-----

Safety:
    A rewrite should "do the right thing" in unexpected circumstances.

    For example, deleting a statement should result in ``pass`` being inserted,
    if that statement is the last statement in the block. Replacing an
    expression should result in additional parentheses if the context requires
    them in order to preserve the parse order.

Ease-of-use:
    Safety aside, everything Refex does was possible beforehand, using tools
    such as :mod:`lib2to3`. Refex aims to be something fun to use, while still
    allowing power users to dig into low level code.

Stdlib :mod:`ast`:
    Many tools write their own AST library, which then needs to be kept up to
    date. Refex aims to use the builtin :mod:`ast` module as the lingua franca
    of code analysis and rewriting.

    (We owe a great debt to the :mod:`asttokens` module for making this
    possible -- and easy.)

    It may be desirable at points to synthetically alter or augment the AST.
    For example, insertion of paren-expression nodes, or comment-line
    statements. All such alterations will, however, be totally ignorable, and
    layered on *top* of the AST as a separate information channel, rather than
    replacing it.

Non-goals
~~~~~~~~~

Speed:
    It is fine if a rewrite across the whole multi-million-line codebase has to
    be done overnight, as long as it is possible to safely perform such a
    rewrite.

Static Analysis:
    Ideally, Refex should be able to consume static analyses which annotate the
    AST, rather than producing such analyses itself.

Multi-language support:
    OK, OK, supporting multiple languages would be pretty rad. This isn't
    ruled out forever -- especially for languages that lack such tools, and are
    also in addition very cool (Rust?)

    But there *are* tools out there, most of the time. Some of them, like
    semgrep, are already general across multiple languages. Where refex excels
    is in being very, very knowledgeable about *Python*, and trafficking in
    standard Python datastructures and modules like :mod:`ast`.

    Refex will gladly support multi-language tools calling into it. It would
    be fantastic if e.g. semgrep utilized Refex as a backend. But the
    other way around might be too ambitious and too much duplication of
    effort.
