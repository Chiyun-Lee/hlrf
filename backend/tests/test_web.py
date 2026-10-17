"""The web app's scripts share one global scope (plain <script> tags in web/index.html): two top-level declarations
with the same name stop the second script from loading."""

import re
from collections import defaultdict
from pathlib import Path

WEB = Path(__file__).parents[2] / "web"
TOP_LEVEL = re.compile(r"^(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Za-z_$][\w$]*)", re.M)


def test_scripts_dont_redeclare_each_others_globals():
    where = defaultdict(list)
    for script in sorted(WEB.glob("*.js")):
        for name in TOP_LEVEL.findall(script.read_text()):
            where[name].append(script.name)
    assert {n: files for n, files in where.items() if len(files) > 1} == {}


def test_web_files_are_revalidated_on_every_load():
    """Without no-cache a browser reuses an old script after an edit, and the page looks unchanged."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    for path in ("/", "/club.js", "/style.css"):
        res = client.get(path)
        assert res.status_code == 200
        assert res.headers["cache-control"] == "no-cache"


# The handwriting is for what's drawn on the paper (doodle notes, figure scribbles, whiteboard text); the interface
# around it uses the plain sans (web/style.css). New views get .title headings and the shared tokens instead.
PAPER_HANDWRITING = {".note", ".marks text, .abstract-slide .mark-text", ".ink-text"}


def test_handwriting_only_on_the_paper():
    css = (WEB / "style.css").read_text()
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    uses = {selector.strip() for selector, body in rules if "var(--hand)" in body}
    assert uses == PAPER_HANDWRITING
    scripts = {s.name for s in WEB.glob("*.js") if re.search(r'class="(?:[^"]* )?hand(?: [^"]*)?"', s.read_text())}
    assert scripts == set()
