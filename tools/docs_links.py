"""MkDocs hook: a link from a page to a file outside docs/ points at that file on GitHub.

The pages link the specification, the headers, the examples and the
changelog by relative paths, which GitHub resolves within the repository.
The site holds only docs/, so the same links there point at the file on
GitHub, at main, from which the site is built.
"""
import posixpath
import re

_LINK = re.compile(r"\]\(([^)\s]+)\)")


def on_page_markdown(markdown, page, config, files):
    blob = config["repo_url"].rstrip("/") + "/blob/main/"
    here = posixpath.join("docs", posixpath.dirname(page.file.src_uri))

    def outside(link):
        target = link.group(1)
        if re.match(r"[a-z]+:|#|/", target):
            return link.group(0)
        path = posixpath.normpath(posixpath.join(here, target))
        if path.startswith("docs/"):
            return link.group(0)
        return "](" + blob + path + ")"

    return _LINK.sub(outside, markdown)
