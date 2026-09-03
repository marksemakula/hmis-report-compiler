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


# ---------------------------------------------------------------------------
# Authored errors must reach the browser, added 3 September 2026.
#
# Reported from production: uploading the week-35 tally returned
# "Upload failed (500): Internal Server Error" and nothing else.
#
# The cause was not a crash. surveillance_index() raises a RuntimeError whose
# message says exactly what to do - "The HMIS 033B data element list is empty.
# The cached DHIS2 metadata predates this report. Set DHIS2_USERNAME and
# DHIS2_PASSWORD (or DHIS2_PAT) and run Refresh metadata in the admin page."
# Nothing caught it, so FastAPI returned a bare 500 and the instruction was
# lost. A configuration problem the operator can fix must never present as a
# crash.
# ---------------------------------------------------------------------------
print("\nA fixable problem must not present as a crash")
src = open(os.path.join(HERE, "..", "api", "index.py")).read()

check("a RuntimeError handler exists",
      "@app.exception_handler(RuntimeError)" in src, True)
check("it answers 503, not 500", 'status_code=503, content={"detail": str(exc)}' in src, True)
check("the authored message is passed through verbatim",
      'content={"detail": str(exc)}' in src, True)

check("the upload dispatch catches RuntimeError itself",
      "except RuntimeError as exc:" in src, True)
check("...and re-raises HTTPException rather than swallowing it",
      "except HTTPException:\n        raise" in src, True)

check("an unexpected exception is still handled",
      "@app.exception_handler(Exception)" in src, True)
# An arbitrary exception can carry a connection string or a token, so its
# message must NOT be echoed to the browser - only its type and the route.
handler = src[src.index("@app.exception_handler(Exception)"):]
handler = handler[:handler.index("# ---------------- auth")]
check("an unexpected exception does NOT echo its message",
      "str(exc)" in handler, False)
check("...but does name the type, so it can be found in the logs",
      "type(exc).__name__" in handler, True)
check("...and states that nothing was saved", "nothing was saved" in handler, True)

# Every library RuntimeError should be worth showing: it should tell the reader
# what to do, not merely what went wrong.
import glob  # noqa: E402
authored = []
for path in glob.glob(os.path.join(HERE, "..", "api", "_lib", "*.py")):
    text = open(path).read()
    for i, line in enumerate(text.splitlines()):
        if "raise RuntimeError(" in line:
            block = " ".join(text.splitlines()[i:i + 6])
            authored.append((os.path.basename(path), block))
actionable = [a for a in authored
              if any(w in a[1] for w in ("Set ", "Run ", "run ", "Check ", "check ",
                                         "configure", "Configure", "expected", "must"))]
check(f"all {len(authored)} library RuntimeErrors tell the reader what to do",
      len(actionable), len(authored))


# ---------------------------------------------------------------------------
# The database must be able to hold what the application can produce.
# Added 3 September 2026.
#
# period was declared VARCHAR(6), sized for a monthly identifier like 202607.
# A weekly one is seven characters - 2026W35 - so uploading a weekly tally
# raised StringDataRightTruncation and the upload failed outright. Weeks 1 to 9
# are six characters and worked, so the fault appeared only from week 10 and
# looked intermittent.
#
# These checks compare every fixed-width column against the longest value the
# code can actually put in it, so a narrow column is caught here rather than by
# someone in a hospital on a Friday afternoon.
# ---------------------------------------------------------------------------
print("\nEvery fixed-width column must hold the longest value the app can write")
import re as _re  # noqa: E402

# This file parses source rather than importing the app, so that it runs with
# nothing installed and cannot be fooled by a module that imports cleanly but
# behaves differently. db.py imports psycopg2 and metadata.py reaches for the
# network, so both are read as text here for the same reason.
# db.py imports psycopg2, which this suite deliberately does not require: the
# checks must run on a laptop with nothing installed. So the schema is read as
# text rather than imported.
dbsrc = open(os.path.join(HERE, "..", "api", "_lib", "db.py")).read()
schema = dbsrc[dbsrc.index("_SCHEMA = "):dbsrc.index("_MIGRATIONS")]
widths = dict(_re.findall(r"(\w+)\s+VARCHAR\((\d+)\)", schema))
widths = {k: int(v) for k, v in widths.items()}

# Longest period identifier the app can generate, across all three cadences.
longest_period = max(
    ["209912", "2099Q4"] + [f"2099W{w}" for w in range(1, 54)], key=len)
check("the schema declares a period column", "period" in widths, True)
check(f"period holds the longest identifier ({longest_period}, "
      f"{len(longest_period)} chars)", widths.get("period", 0) >= len(longest_period), True)
check("period has headroom beyond the longest known identifier",
      widths.get("period", 0) >= len(longest_period) + 4, True)

mdsrc = open(os.path.join(HERE, "..", "api", "_lib", "metadata.py")).read()
report_codes = _re.findall(r'^\s*"([A-Z]{2,8})":\s*\{"dataSet":', mdsrc, _re.M)
check(f"found the registered report codes ({len(report_codes)})",
      len(report_codes) >= 8, True)
longest_type = max(report_codes, key=len)
check(f"report_type holds the longest report code ({longest_type})",
      widths.get("report_type", 0) >= len(longest_type), True)

# Audit actions are literals scattered through index.py; an over-long one would
# fail the very request it was meant to record.
actions = _re.findall(r'db\.audit\([^,]+,\s*"([^"]+)"', src)
check(f"{len(actions)} audit actions all fit the action column",
      [a for a in actions if len(a) > widths.get("action", 64)], [])

# Status vocabularies, read from the code that writes them.
statuses = set(_re.findall(r'push_status["\']?\s*[:=]\s*["\']([A-Z_]+)["\']', src)) | {
    "DRAFT", "PUSHED", "FAILED", "DRY_RUN", "PENDING"}
check("every push status fits",
      [s for s in statuses if len(s) > widths.get("push_status", 16)], [])
sources = {"UPLOAD", "SCRIPT", "AGENT"}
check("every import source fits", [s for s in sources if len(s) > 32], [])

print("\nAn existing database must be migrated, not just newly created correctly")
# CREATE TABLE IF NOT EXISTS leaves an existing table untouched, so widening the
# declaration alone would fix nothing for the deployment that already has data.
check("a migration block exists", "_MIGRATIONS" in dbsrc, True)
check("it widens imported_data.period",
      "ALTER TABLE imported_data ALTER COLUMN period TYPE VARCHAR(16)" in dbsrc, True)
check("it widens reports.period",
      "ALTER TABLE reports       ALTER COLUMN period TYPE VARCHAR(16)" in dbsrc, True)
check("the migrations actually run at start-up",
      "cur.execute(_MIGRATIONS)" in dbsrc, True)
check("migrations are idempotent (ALTER TYPE only, no destructive statement)",
      [ln for ln in dbsrc[dbsrc.index("_MIGRATIONS"):dbsrc.index("_initialised")].splitlines()
       if ln.strip() and ln.strip().startswith(("DROP", "DELETE", "TRUNCATE"))], [])
