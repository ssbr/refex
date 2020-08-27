Merged fixes
============

Sometimes, multiple fixes apply to the same span of code. For example, we might
want a fixer to replace ``deprecated($x)`` with ``nondeprecated($x)``. So what
if we see the line ``deprecated(deprecated(0))``?

One approach, which Refex often follows, is to suggest multiple rewrites. This
works great if they do not overlap at all -- perhaps if we just replace the span
``deprecated`` with ``nondeprecated``. But if they do overlap, Refex will
iteratively try to apply as many fixes as it can in one go.

The resulting message might be a bit confusing. We concatenate all the
"important" messages together with their explanatory URLs. The "unimportant"
ones are generally for trivial fixes that don't really matter in context -- e.g.
a spelling correction.
