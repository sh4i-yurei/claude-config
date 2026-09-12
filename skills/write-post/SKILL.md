---
name: write-post
description: Drafts a blog post for keepbreath.ing from a buildlog in Mark's vault at ~/Documents/Second_Brain. Use this when he wants to write up, draft, or turn work into a post, when he asks what is worth writing about or what he should blog next, when a buildlog is finished and marked post candidate, and when he mentions the blog, an article, or publishing something. Also use it when work you just did together clearly has a story in it worth telling. Trigger it even when he does not name the vault or a buildlog.
---

# Writing a post

Mark's technical posts are built almost entirely out of things that went wrong. Not
"I hit a problem and fixed it" — the specific symptom, the specific cause, the
specific fix. Curl returned nothing because `localhost` resolved to IPv6 while
rootless podman had bound IPv4 only. HSTS stayed at 300 because `git pull` replaced
the file and Docker's bind mount was pinned to the orphaned inode. `ufw` read
correctly and did nothing because Docker writes its own iptables rules.

Those are the posts. Everything else is scaffolding around them.

## Find the material

```bash
python3 ~/.claude/skills/vault-query/scripts/query.py buildlogs --post candidate
```

Then read both files in that buildlog folder. The **outline** gives structure — the
angle, who it's for, the intended section arc. The **log** gives substance — what
actually happened, in order, with the real commands and real output.

If the log is thin, say so before starting. A post written from a thin log gets
written from memory, and that is where the specific detail quietly turns into
generic advice.

## Which template

`_Templates/post-technical.md` for anything built from a buildlog. Opens with what
changed, then narrative sections in the order things actually happened, then a
**What I learned** section that digests the gotchas into one-liners, then a pointer
at what's next if there is one.

`_Templates/post-personal.md` for pieces with no code — the career change, going
back to school. No gotcha digest, no section structure required, allowed to end
unresolved. Source material is `[life]` entries and memory, not a command log.

Never staple the technical structure onto a personal piece.

## Writing it

**Not every entry in the log goes in the post.** The log records everything because
it has to; the post keeps what changed something or taught something. A missing
editor, a terminal variable, a paste that landed twice, a key that looked clipped
and was not: those are hiccups with one-line fixes that altered nothing, and they
read as padding no matter how well they are written. Before keeping a failure, ask
what the reader has after it that they did not have before. If the answer is a
shell flag, cut it. Judge by the cause, not the word count: a paste into the wrong
terminal, a prompt that timed out because he looked away, a command typed on the
wrong box. Those have no cause a reader can learn from, however good the error text
looks, and dressing one up with ICANN and loopback addresses makes it worse, not
better. A [life] entry earns its place by being about the person; a
hiccup does not become life color by being small.

**A [life] entry never becomes a paragraph of its own.** Pasting one in as a block,
between two technical paragraphs, is jarring, and it reads as the log rather than
as a story. Life detail is salt: it goes into the sentence where the day starts ("I
started on Labor Day, late, after class and a family gathering"), the sentence where
it ends ("by then it was three in the morning, with class in a few hours"), or the
sentence it interrupted ("I sat down to write the inventory and never got to it").
Split one entry across two places if that is where the moments happened. The test
is whether a reader could tell the paragraph came from a separate list.

**The asides are his to write, and the draft should leave room for them.** This is
what one looks like, from his own edit of the bastion post: "I had said an hour at
ten to eleven and it was ten to one. Seems like the clock always goes faster than I
expect. I guess time flies when you're having fun....or whatever it was my parents
used to say." It is not a fact about the build and it is not a lesson. It is him
noticing something about himself, with a saying he half-remembers and does not
finish. Do not invent these; a fabricated aside in his voice is worse than none.
When a paragraph lands on a moment (a time, a coffee, a bedtime), stop there and
mark it in the handoff as a place he may want to say something, rather than closing
the paragraph with a tidy sentence of your own.

**Sections are beats, not categories.** Title them after the event: "Security
headers, and the Google Fonts trap." "Then the ball went straight through the
paddle." Not "Configuration" and "Testing."

**Show the real command and the real output**, trimmed to the interesting few
lines. A code block nobody can read is decoration.

**Explain any term a reader might not have** — inodes, origin certificates,
cattle-not-pets — inline, in one sentence, without condescending. He does this
consistently and it is a large part of why the posts work.

**Keep the honest reason.** "Because nginx is the tool used everywhere in security
work and I want to know it" beats a performance justification neither of you
believes.

**Link out** to real documentation where a reader would want to go deeper.

**A claim about someone else's product is either verified or hedged.** "There is no
narrower permission," "every droplet gets a VPC by default," "most tutorials do X."
If the draft states how GitHub, DigitalOcean, Google or a library behaves, either
fetch the documentation, confirm it, and link it, or write "to my knowledge" or "as
far as I can tell" in front of it. An absolute assertion Mark cannot back up goes
out under his name, and a reader who knows better stops trusting the rest.

## Voice

Read a published post before drafting — `30_Posts/migrating-to-nginx.md` for
technical, `30_Posts/why-i-went-back-to-school-at-46.md` for personal. Direct, first
person, short declarative sentences, dry about his own mistakes. No emoji in
finished posts, no throat-clearing, no "in this post I will."

The draft is his to rewrite. Getting the structure and the facts right matters more
than getting the sentences right — but do not flatten his voice into generic tech
blogging, because that is the failure he will notice.

## Screenshots

The buildlog's `images/` folder holds what was captured during the work. Embed them
with `![[filename.png]]` so they render and stop showing up as orphan attachments.
Check for anything needing redaction — IPs, emails, tokens — before it goes near
the site.

## Second pass, before the draft goes back to Mark

A first draft written from a log comes out with AI tells in it every time: a moral
at the end of each paragraph, "not X but Y" contrasts, a tidy triad where two items
would do, and vault words like "notes" and "project note" that mean nothing to a
reader. Three tools catch these, and they run in this order, each on the file in
place. Do not skip any of them and do not hand over the draft until all three have
run.

1. **`humanizer` skill.** Load it and work through its pattern list against the
   whole post. It is built from Wikipedia's "Signs of AI writing" and it catches the
   structural tells the directive does not name. Use its voice-calibration mode with
   two of Mark's published posts from `30_Posts` as the sample, so it edits toward
   his voice and not toward a generic human one.
2. **`blog-writing-guide` skill.** Sentry's editorial checklist, scoped locally to
   review only. Apply its AI-patterns list, the heading rule (every heading carries
   information), numbers over adjectives, the opening and closing rules, and the two
   review checklists. Ignore its SEO, byline, post-type and "we" sections; the note
   at the top of that skill says which is which.
3. **Vale**, which runs on its own from the PostToolUse hook every time the post is
   written or edited, and by hand with `vale 30_Posts/<slug>.md` from the vault
   root. It is a program, not a judgement, and it only knows vocabulary and sentence
   shapes. Its findings are suggestions: fix the real ones, and if a rule keeps
   firing on ordinary English for this genre, switch it off in `.vale.ini` with the
   reason written next to it rather than working around it in the prose.

None of the three tools catch **false surprise**, so check for it by hand: a default,
a provider feature, or something Mark built himself, described as if it were found
or lucky. "The private network path already worked." "This time there was something
to check against." "`AllowTcpForwarding` was already on." Every droplet in a region
shares a VPC, OpenSSH forwards by default, and a laptop that has been connecting to
a box for two weeks has its fingerprint. Say what the thing is and why it is there,
in the same tone as any other fact. Surprise is for things that were a surprise.

Then read the whole post once more as a stranger, and check the timeline against the
log's timestamps line by line. A blog post never mentions the vault, the notes, the
project note, the facts table, or the procedure. Those are how the work was
recorded, not how it was done.

## Finishing

Save to `30_Posts/<slug>.md` with `status: drafted`, `genre:`, and links back to the
`project:` and `buildlog:`. Set `series:` if it belongs to a thread — his posts
chain, and the nginx one already ends by pointing at the droplet rebuild.

Then update the buildlog's `post:` to `drafted`, so the candidate search stops
returning work that's already been written up.

Publishing is separate and manual: hand-coded into `site/blog.html` in the
keepbreathing repo, images copied to `site/images/blog/<slug>/`, deployed via the PR
workflow, then Cloudflare cache purged. The markdown here stays the source of record.
