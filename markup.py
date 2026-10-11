"""Discord-style formatting for doctrine descriptions and fit notes.

Supports: **bold**, *italic* / _italic_, ***bold italic***, __underline__,
~~strike~~, `code`, ```code blocks```, [links](https://...), bare links,
# / ## / ### headings, -# small text, - / * / • bullet lists,
1. numbered lists and > quotes. Everything is HTML-escaped first, so no raw
HTML from the text ever reaches the page.
"""
import re

from markupsafe import Markup, escape

CODE_RE = re.compile(r"`([^`\n]+)`")
LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
URL_RE = re.compile(r"(?<![\"'=>])\b(https?://[^\s<]+[^\s<.,:;!?)\]'\"])")
BULLET_RE = re.compile(r"^\s*(?:[-*•])\s+(.*)$")
NUMBER_RE = re.compile(r"^\s*(\d{1,3})[.)]\s+(.*)$")
HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
SUBTEXT_RE = re.compile(r"^-#\s+(.*)$")
QUOTE_RE = re.compile(r"^>\s?(.*)$")

INLINE_RULES = [
    (re.compile(r"\*\*\*(?=\S)(.+?)(?<=\S)\*\*\*"), r"<strong><em>\1</em></strong>"),
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"__(?=\S)(.+?)(?<=\S)__"), r"<u>\1</u>"),
    (re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"), r"<s>\1</s>"),
    (re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])"), r"<em>\1</em>"),
    (re.compile(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])"), r"<em>\1</em>"),
]


def _inline(raw):
    """Format one line of text. Input is raw text, output is safe HTML."""
    stash = []

    def keep(html):
        stash.append(html)
        return f"\x00{len(stash) - 1}\x00"

    text = str(escape(raw))
    text = CODE_RE.sub(lambda m: keep(f"<code>{m.group(1)}</code>"), text)
    text = LINK_RE.sub(lambda m: keep(
        f'<a href="{m.group(2)}" target="_blank" rel="noopener nofollow">{m.group(1)}</a>'), text)
    text = URL_RE.sub(lambda m: keep(
        f'<a href="{m.group(1)}" target="_blank" rel="noopener nofollow">{m.group(1)}</a>'), text)
    for pattern, repl in INLINE_RULES:
        text = pattern.sub(repl, text)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def render(text):
    """Turn Discord-style text into safe HTML."""
    if not text:
        return Markup("")
    lines = text.replace("\r\n", "\n").split("\n")
    out, para, list_tag, list_items, quote = [], [], None, [], []

    def flush_para():
        if para:
            out.append("<p>" + "<br>".join(_inline(l) for l in para) + "</p>")
            para.clear()

    def flush_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"<{list_tag}>" + "".join(f"<li>{_inline(i)}</li>" for i in list_items) + f"</{list_tag}>")
            list_items.clear()
            list_tag = None

    def flush_quote():
        if quote:
            out.append("<blockquote>" + "<br>".join(_inline(l) for l in quote) + "</blockquote>")
            quote.clear()

    def flush_all():
        flush_para()
        flush_list()
        flush_quote()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):  # fenced code block
            flush_all()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            out.append(f"<pre><code>{escape(chr(10).join(body))}</code></pre>")
            i += 1
            continue

        if not stripped:
            flush_all()
        elif m := SUBTEXT_RE.match(stripped):
            flush_all()
            out.append(f'<p class="subtext">{_inline(m.group(1))}</p>')
        elif m := HEADING_RE.match(stripped):
            flush_all()
            level = len(m.group(1)) + 2  # # -> h3, ## -> h4, ### -> h5
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
        elif m := BULLET_RE.match(line):
            flush_para()
            flush_quote()
            if list_tag != "ul":
                flush_list()
                list_tag = "ul"
            list_items.append(m.group(1))
        elif m := NUMBER_RE.match(line):
            flush_para()
            flush_quote()
            if list_tag != "ol":
                flush_list()
                list_tag = "ol"
            list_items.append(m.group(2))
        elif m := QUOTE_RE.match(stripped):
            flush_para()
            flush_list()
            quote.append(m.group(1))
        else:
            flush_list()
            flush_quote()
            para.append(stripped)
        i += 1
    flush_all()
    return Markup("\n".join(out))


def plain(text):
    """Strip formatting for short previews (cards, link previews)."""
    if not text:
        return ""
    t = LINK_RE.sub(r"\1", text)
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"^\s*(?:#{1,3}|-#|>|[-*•]|\d{1,3}[.)])\s+", "", t, flags=re.M)
    t = re.sub(r"(\*\*\*|\*\*|__|~~|`)", "", t)
    t = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", r"\1", t)
    t = re.sub(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()
