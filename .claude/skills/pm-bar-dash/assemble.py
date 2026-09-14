#!/usr/bin/env python3
"""Assemble template/{head,body,script}.html + dash.json into one standalone page.

    python3 assemble.py <dash.json> <out.html>
"""
import json, os, sys

D = os.path.dirname(os.path.abspath(__file__))
T = os.path.join(D, "template")


def rd(n):
    return open(os.path.join(T, n)).read()


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, out = sys.argv[1], sys.argv[2]
    data = open(src).read()
    json.loads(data)                       # fail loudly on malformed input
    # escaped '<' can never open a tag inside the JSON island
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    assert "</script" not in data.lower()
    html = rd("head.html") + "\n" + rd("body.html") + "\n" + rd("script.html").replace("__DATA__", data)
    open(out, "w").write(html)
    print(f"wrote {out} ({os.path.getsize(out)//1024} KB)")


if __name__ == "__main__":
    main()
