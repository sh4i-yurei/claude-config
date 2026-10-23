"""Quote corrections for the unmodified vendored bashlex 0.18 parser.

bashlex keeps quotes in here-document delimiter words, though Bash removes them
before comparing input lines. It also retains inner quote escapes in nested
shell script words. Keep both corrections here so vendor/bashlex remains upstream.
"""

import shlex

import bashlex.heredoc


def install():
    original = bashlex.heredoc.makeheredoc

    def makeheredoc(tokenizer, redirnode, lineno, killleading):
        word = redirnode.output.word
        decoded = shlex.split(word)
        if len(decoded) == 1:
            redirnode.output.word = decoded[0]
        try:
            return original(tokenizer, redirnode, lineno, killleading)
        finally:
            redirnode.output.word = word

    bashlex.heredoc.makeheredoc = makeheredoc


def word_value(node, source):
    raw = source[node.pos[0] : node.pos[1]]
    try:
        decoded = shlex.split(raw)
    except ValueError:
        return node.word
    return decoded[0] if len(decoded) == 1 else node.word
