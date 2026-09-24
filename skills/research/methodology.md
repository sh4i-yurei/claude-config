# Research methodology

Reference for the `research` skill. Read this when actually doing a research pass, not to
decide whether to.

The techniques come from systematic review practice, where covering a field completely is
the whole job, and from published work on why automated research loops either run forever
or stop after two searches.

## Why keyword search alone comes out shallow

A genuinely relevant source may use different terminology, sit in an adjacent field's
vocabulary, or predate the term being searched for. Keyword search cannot see any of those.
That is the mechanism behind every shallow answer — not laziness, but a method that can only
return things already phrased the way the question was.

The techniques below exist to reach what the words missed.

## Citation and link chaining

Once a good source is found, stop searching and chain from it.

**Backward** means following what that source cites or links to. It reaches only older
material, so it cannot be the whole method.

**Forward** means finding what has cited or linked to it since. This is where replications,
critiques, applications and current status live, and it is the step most often skipped.

For papers, forward chaining means a citation index. For code and standards, it means
"used by" listings, dependent repositories, issue threads that reference the project, and
posts that link to it.

Two pitfalls. Different indexes cover different slices, so never treat one tool's count as
definitive. And a very recent source with nothing citing it is indexing lag, not
irrelevance.

## Reaching the unindexed layer

Search rankings favour what was written to be found. Over-reliance on that biases toward
the promotional layer of any topic.

Go looking deliberately for: issue trackers, mailing list archives, changelogs, release
notes, commit history, specification documents in the repository itself, and forum threads.
For a contested technical claim this is usually where the disagreement actually lives,
because critics rarely write blog posts.

Expect some of it to be gated. Several archives now sit behind proof-of-work bot
challenges. The answer is a different source or a mirror, not a harder scraper.

## Judging saturation

The stopping rule is saturation: keep chaining from newly added relevant sources until a
full round adds nothing new, then stop. Stop a branch when it stops returning anything new
and relevant, rather than after a fixed number of rounds.

Capping depth deliberately is legitimate. Letting an unstated cap pass as saturation is not.
Say which one happened.

A budget alone is not a stopping rule. It prevents runaway cost and produces exactly the
same shallow output as a single search if nothing else is doing the work. Coverage is what
decides when to stop; the budget only guarantees that it terminates.

## Judging what comes back

Between half and ninety per cent of citations produced by a language model are not fully
supported by the source they point at. Even with live search, roughly thirty per cent of
statements come out unsupported. Assume this applies to your own output.

- Two independent sources for any load-bearing claim.
- Weight specifications, papers and official documentation above blogs and forums.
- When sources disagree, flag the conflict rather than silently choosing.
- Record where a source has an interest. A vendor's own benchmark is evidence about the
  vendor, not about the product.

The trap specific to iterative research: a wrong claim picked up early redirects everything
after it, so the session builds on a false premise while looking productive. Re-check the
claims that later searches were built on.

## Writing it down as you go

A research pass easily exceeds what fits in a context window, and anything held only there
is lost as the session grows. Write findings to the topic note as they arrive rather than
assembling everything at the end.

Record, per source: the date, the exact query, and the tool used. That is what makes the
search reproducible and criticisable later, and it costs nothing at the time.
