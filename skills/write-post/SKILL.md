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

## Finishing

Save to `30_Posts/<slug>.md` with `status: drafted`, `genre:`, and links back to the
`project:` and `buildlog:`. Set `series:` if it belongs to a thread — his posts
chain, and the nginx one already ends by pointing at the droplet rebuild.

Then update the buildlog's `post:` to `drafted`, so the candidate search stops
returning work that's already been written up.

Publishing is separate and manual: hand-coded into `site/blog.html` in the
keepbreathing repo, images copied to `site/images/blog/<slug>/`, deployed via the PR
workflow, then Cloudflare cache purged. The markdown here stays the source of record.
