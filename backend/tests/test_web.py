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
