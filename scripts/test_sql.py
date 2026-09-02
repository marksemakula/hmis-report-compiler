"""Static checks on the discovery scripts under scripts/sql/.

These scripts are handed to someone to paste into Azure Data Studio against a
live hospital database. We never see them run, and a mistake costs a round trip
measured in hours. Two classes of mistake have already happened:

  1. A dynamic-SQL string whose quotes did not balance, so the generated
     statement was a syntax error.
  2. A static reference to a column that did not exist. That one is worse than
     it sounds: an invalid column name is a COMPILE-time binding error, and SQL
     Server binds the whole batch before running any of it. TRY/CATCH does not
     help - the entire script failed and returned nothing, including the six
     sections that were correct.

So the rules enforced here are: anything touching a table whose shape we have
not confirmed goes through sp_executesql, where compilation is deferred into the
TRY; and every generated statement must be quote-balanced and shaped like an
INSERT into the temp table.

Also asserts the scripts are read-only against the clinical database. They run
against production records at a regional referral hospital under a login that
may well have write rights.

    python scripts/test_sql.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SQL_DIR = os.path.join(HERE, "sql")

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


def read_literal(s, i):
    """T-SQL string literal starting at the quote s[i]. Returns (text, next_index)."""
    i += 1
    out = []
    while i < len(s):
        if s[i] == "'":
            if i + 1 < len(s) and s[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), i + 1
        out.append(s[i])
        i += 1
    raise ValueError("unterminated string literal")


SUBS = {
    "@cols": " + ' | ' + ISNULL(CONVERT(varchar(100), [Col]), '')",
    "@sec": "section_name",
    "@lbl": "e.SubTestCode",
    "@tbl": "TableName",
}


def generated_statements(src):
    """Evaluate every `SET @sql = N'...' + @var + N'...'` as SQL Server would."""
    out = []
    idx = 0
    while True:
        idx = src.find("SET @sql = ", idx)
        if idx < 0:
            return out
        i = idx + len("SET @sql = ")
        parts = []
        while i < len(src):
            while i < len(src) and src[i] in " \n\r\t":
                i += 1
            if i < len(src) and src[i] == "N":
                i += 1
            if i < len(src) and src[i] == "'":
                lit, i = read_literal(src, i)
                parts.append(lit)
            elif i < len(src) and src[i] == "@":
                j = i
                while j < len(src) and src[j] not in " \n+;":
                    j += 1
                parts.append(SUBS.get(src[i:j], "?UNKNOWN?"))
                i = j
            elif src.startswith("QUOTENAME(@tbl)", i):
                parts.append("[TableName]")
                i += len("QUOTENAME(@tbl)")
            else:
                break
            while i < len(src) and src[i] in " \n\r\t":
                i += 1
            if i < len(src) and src[i] == "+":
                i += 1
                continue
            break
        out.append("".join(parts))
        idx = i


scripts = sorted(f for f in os.listdir(SQL_DIR) if f.endswith(".sql"))
print(f"\n{len(scripts)} script(s) under scripts/sql/")

for name in scripts:
    src = open(os.path.join(SQL_DIR, name)).read()
    print(f"\n{name}")

    # --- read-only ---------------------------------------------------------
    # Writes are permitted only against the temp table each script builds.
    writes = re.findall(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO)\s+(\S+)",
                        src, re.I)
    bad = [t for _, t in writes if not t.lstrip("(").startswith("#")]
    check("every write targets a temp table", bad, [])

    ddl = re.findall(r"\b(ALTER|TRUNCATE|GRANT|REVOKE)\b", src, re.I)
    check("no schema or permission changes", ddl, [])

    drops = re.findall(r"\bDROP\s+TABLE\s+(\S+)", src, re.I)
    check("only temp tables are dropped",
          [d for d in drops if not d.startswith(("#", "tempdb"))], [])

    execs = re.findall(r"\bEXEC(?:UTE)?\s+(\w+)", src, re.I)
    check("the only procedure executed is sp_executesql",
          sorted({e.lower() for e in execs} - {"sp_executesql"}), [])

    # --- one grid ----------------------------------------------------------
    # Azure Data Studio saves one grid per CSV, so a script returning several
    # loses all but the first - which cost two round trips before every script
    # was made to return exactly one. A SELECT returns a grid unless it is
    # feeding an INSERT or assigning to a variable, so those are stripped and
    # what remains must be a single statement-initial SELECT.
    stripped = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)          # block comments
    stripped = re.sub(r"--[^\n]*", " ", stripped)                  # line comments
    stripped = re.sub(r"N?'(?:[^']|'')*'", "''", stripped)         # string literals
    stripped = re.sub(r"\bINSERT\s+INTO\s+#\w+[^;]*?\bSELECT\b", " ", stripped, flags=re.I | re.S)
    stripped = re.sub(r"\bSELECT\s+@\w+\s*=", " ", stripped, flags=re.I)
    grids = [m for m in re.finditer(r"\bSELECT\b", stripped, re.I)
             if re.search(r"(?:^|[;\)]|\bBEGIN\b|\bEND\b)\s*$", stripped[:m.start()], re.I)]
    check("returns a single result grid", len(grids), 1)

    # --- dynamic SQL -------------------------------------------------------
    stmts = generated_statements(src)
    if not stmts:
        print("  --    no dynamic SQL")
        continue
    for n, gen in enumerate(stmts, start=1):
        head = gen.lstrip().upper()
        check(f"generated statement {n} has balanced quotes", gen.count("'") % 2, 0)
        # Two legitimate shapes: writing into the temp table, or assigning a
        # scalar into an OUTPUT variable (which 08_db_profile does throughout).
        check(f"generated statement {n} writes to a temp table or a variable",
              head.startswith("INSERT INTO #") or
              re.match(r"SELECT\s+@\w+\s*=", head) is not None, True)
        check(f"generated statement {n} contains no unresolved variable",
              "?UNKNOWN?" in gen, False)
        # The mistake this catches: a concatenation assembled from sys.columns
        # begins with "+ ' | ' + ..." and needs something to attach to. Left
        # unseeded it is a syntax error, and it is invisible in the source
        # because the fragment only appears once the string is built.
        dangling = re.search(r"[(,]\s*\+\s*'", gen)
        check(f"generated statement {n} has no operand-less concatenation",
              dangling.group(0) if dangling else None, None)

print()
if failures:
    print(f"{len(failures)} check(s) failed:\n")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
