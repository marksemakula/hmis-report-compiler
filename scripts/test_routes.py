"""Static check for FastAPI route shadowing.

FastAPI matches routes in declaration order. A literal path declared *after* a
parameterised sibling with the same shape is unreachable: the parameterised
route wins, and if its parameter is typed the request dies with 422 rather than
404 - which reads like a validation bug rather than a routing one, and costs an
afternoon to find.

This is exactly what happened to /api/py/reports/types, shadowed by the earlier
/api/py/reports/{report_id}. Parsing the source rather than importing the app
keeps the check free of psycopg2, jwt and the rest of the runtime.

    python scripts/test_routes.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "..", "api", "index.py")

DECORATOR_RE = re.compile(
    r'^@app\.(get|post|put|patch|delete)\(\s*[\'"]([^\'"]+)[\'"]', re.M)

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


def segments(path):
    return [p for p in path.strip("/").split("/") if p != ""]


def is_param(seg):
    return seg.startswith("{") and seg.endswith("}")


def shadows(earlier, later):
    """Would `earlier` swallow a request intended for `later`?"""
    a, b = segments(earlier), segments(later)
    if len(a) != len(b):
        return False
    saw_param_over_literal = False
    for sa, sb in zip(a, b):
        if sa == sb:
            continue
        if is_param(sa) and not is_param(sb):
            saw_param_over_literal = True
            continue
        return False
    return saw_param_over_literal


with open(SOURCE) as f:
    src = f.read()

routes = [(m.group(1).upper(), m.group(2)) for m in DECORATOR_RE.finditer(src)]

print(f"\nParsed {len(routes)} route declarations from api/index.py")
check("routes were found", len(routes) > 10, True)

print("\nNo literal path may be shadowed by an earlier parameterised sibling")
problems = []
for i, (method, path) in enumerate(routes):
    for earlier_method, earlier_path in routes[:i]:
        if earlier_method == method and shadows(earlier_path, path):
            problems.append(f"{method} {path} is shadowed by earlier {earlier_method} {earlier_path}")
for p in problems:
    print("  FAIL  " + p)
check("no shadowed routes", problems, [])

print("\nDuplicate declarations")
seen, dupes = set(), []
for method, path in routes:
    if (method, path) in seen:
        dupes.append(f"{method} {path}")
    seen.add((method, path))
check("no duplicate route declarations", dupes, [])

print("\nThe shadowing detector itself")
check("param over literal shadows", shadows("/a/{id}", "/a/types"), True)
check("identical paths do not count", shadows("/a/types", "/a/types"), False)
check("different depth is safe", shadows("/a/{id}", "/a/b/c"), False)
check("literal before param is safe", shadows("/a/types", "/a/{id}"), False)
check("preview status is safe alongside preview",
      shadows("/api/py/preview/{t}/status", "/api/py/preview/{t}"), False)
check("the original bug would have been caught",
      shadows("/api/py/reports/{report_id}", "/api/py/reports/types"), True)

print("\nThe backwards-compatible alias must sit ABOVE the parameterised route")
order = [p for m, p in routes if m == "GET"]
if "/api/py/reports/types" in order and "/api/py/reports/{report_id}" in order:
    check("alias is declared before /api/py/reports/{report_id}",
          order.index("/api/py/reports/types") < order.index("/api/py/reports/{report_id}"),
          True)
else:
    check("alias and parameterised route both declared",
          ("/api/py/reports/types" in order, "/api/py/reports/{report_id}" in order),
          (True, True))

print("\nThe preview endpoints the front end calls must exist")
declared = {f"{m} {p}" for m, p in routes}
for wanted in [
    "GET /api/py/report-types",
    "GET /api/py/preview/{report_type}",
    "GET /api/py/preview/{report_type}/status",
    "POST /api/py/forms/refresh",
]:
    check(f"declared: {wanted}", wanted in declared, True)

print("\nFront-end fetches resolve to declared routes")
paths = {p for _, p in routes}


def matches_a_route(url):
    want = segments(url.split("?")[0])
    for p in paths:
        got = segments(p)
        if len(got) != len(want):
            continue
        if all(is_param(g) or g == w for g, w in zip(got, want)):
            return True
    return False


app_dir = os.path.join(HERE, "..", "app")
called = set()
for root, _dirs, files in os.walk(app_dir):
    for name in files:
        if not name.endswith(".js"):
            continue
        with open(os.path.join(root, name)) as f:
            body = f.read()
        for m in re.finditer(r"['\"`](/api/py/[^'\"`\s]*)['\"`]", body):
            called.add(m.group(1))
        for m in re.finditer(r"`(/api/py/[^`]*)`", body):
            called.add(re.sub(r"\$\{[^}]*\}", "X", m.group(1)))

for url in sorted(called):
    check(f"front end calls a real route: {url[:46]}", matches_a_route(url), True)

print()
if failures:
    print(f"{len(failures)} check(s) failed:\n")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
