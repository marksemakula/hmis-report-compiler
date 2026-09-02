"""Checks for the laboratory result vocabulary.

Every string asserted below was observed in ClinicMasterMOH at Jinja on
2 September 2026, with its real frequency in the comment. This is not a
hypothetical vocabulary — it is the one the compiler will meet.

Two orderings must hold and they pull against each other:

    NON REACTIVE            contains REACTIVE      -> negatives first
    MTB DETECTED ...,       contains NOT DETECTED  -> leading clause only

Get the first wrong and every syphilis screen reports positive. Get the second
wrong and every Xpert-positive reports negative. Both would be invisible in a
total and catastrophic in a notification.

    python scripts/test_lab.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))

from _lib import lab  # noqa: E402

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


P, N, I, X = lab.POSITIVE, lab.NEGATIVE, lab.INVALID, lab.INDETERMINATE

print("\nMalaria microscopy, as actually recorded")
for raw, want, seen in [
    ("NO MPS SEEN", N, 2975),
    ("MPS + SEEN", P, 602),
    ("MPS ++ SEEN", P, 123),
    ("MPS +++ SEEN", P, 10),
    ("No Plasmodium Parasites", N, 15),
]:
    check(f"{raw!r} ({seen} observed)", lab.classify(raw), want)

check("grade of a clean smear", lab.parasite_grade("NO MPS SEEN"), 0)
check("grade +", lab.parasite_grade("MPS + SEEN"), 1)
check("grade ++", lab.parasite_grade("MPS ++ SEEN"), 2)
check("grade +++", lab.parasite_grade("MPS +++ SEEN"), 3)
check("grade of a non-answer", lab.parasite_grade("0"), None)

print("\nThe REACTIVE trap: negatives must be read before positives")
for raw, want, seen in [
    ("NON-REACTIVE", N, 437),      # TPHA
    ("Non Reactive", N, 154),      # RPR
    ("NON REACTIVE", N, 10),       # HIV serology
    ("REACTIVE", P, 13),           # TPHA
]:
    check(f"{raw!r} ({seen} observed)", lab.classify(raw), want)

print("\nThe NOT DETECTED trap: only the leading clause is the answer")
for raw, want, seen in [
    ("MTB NOT DETECTED", N, 78),
    ("NOT DETECTED", N, 17),
    ("MTB DETECTED MEDIUM,RIF resistance NOT DETECTED", P, 9),
    ("MTB DETECTED LOW,RIF resistance NOT DETECTED", P, 5),
]:
    check(f"{raw!r} ({seen} observed)", lab.classify(raw), want)

print("\n...and resistance is a separate question from the same string")
check("medium load, not resistant",
      lab.rifampicin_resistant("MTB DETECTED MEDIUM,RIF resistance NOT DETECTED"), False)
check("low load, not resistant",
      lab.rifampicin_resistant("MTB DETECTED LOW,RIF resistance NOT DETECTED"), False)
check("resistant", lab.rifampicin_resistant("MTB DETECTED HIGH,RIF resistance DETECTED"), True)
check("a negative says nothing about resistance",
      lab.rifampicin_resistant("MTB NOT DETECTED"), None)
check("neither does a bare result", lab.rifampicin_resistant("NEGATIVE"), None)

print("\nThe controlled list's own misspellings must be accepted")
# POSTIVE is the spelling stored in LabPossibleResults for HIV serology,
# HBsAg, TPHA, HCG-BETA and malaria RDT, so it reaches the data through the
# dropdown. Negaitve/Positve likewise, for blood grouping.
for raw, want in [("POSTIVE", P), ("POSITIVE", P), ("Positve", P),
                  ("NEGATIVE", N), ("Negaitve", N), ("INVALID", I),
                  ("INCONCLUSIVE", X)]:
    check(f"{raw!r}", lab.classify(raw), want)

print("\nEverything else observed in the reportable tests")
for raw, want, note in [
    ("NEGATIVE", N, "HBsAg 457, MRDT 278, Determine 190, TB-LAM 65"),
    ("POSITIVE", P, "HBsAg 107, MRDT 45, Determine 22, TB-LAM 15"),
]:
    check(f"{raw!r} ({note})", lab.classify(raw), want)

print("\nShort abbreviations must match as whole words, not as substrings")
check("POS on its own is positive", lab.classify("POS"), P)
check("NEG on its own is negative", lab.classify("NEG"), N)
check("POS inside POSTPARTUM is not a result", lab.classify("POSTPARTUM SPECIMEN"), None)
check("NEG inside NEGLECT is not a result", lab.classify("NEGLECTED SAMPLE"), None)
check("DETECTED still matches inside a phrase",
      lab.classify("MTB DETECTED HIGH"), P)

print("\nNon-answers must not be counted either way")
for raw in ["", "   ", None, "0", "120", "299", "< 200", "> 200", "5.5", "N/A", "--"]:
    check(f"{raw!r} yields no verdict", lab.classify(raw), None)

print("\nNumeric results")
check("CD4 count", lab.numeric_value("120"), 120.0)
check("below the limit of quantification", lab.numeric_value("< 200"), 200.0)
check("above it", lab.numeric_value("> 200"), 200.0)
check("thousands separator", lab.numeric_value("1,250"), 1250.0)
check("nothing numeric", lab.numeric_value("NEGATIVE"), None)
check("CD4 is a measurement", lab.is_numeric_test("313660005"), True)
check("viral load is a measurement", lab.is_numeric_test("315124004"), True)
check("HBsAg is not", lab.is_numeric_test("47758006"), False)

print("\nThe right analyte, and only the right one")
check("malaria microscopy reads Detection", lab.reportable_subtest("372071003"), "01")
check("HIV serology reads Determine", lab.reportable_subtest("165813002"), "kizxvo8k")
check("Xpert reads MTB, not RIF Resistance", lab.reportable_subtest("9000001"), "ma7dy01a")
check("a full blood count is not reportable here", lab.reportable_subtest("26604007"), None)
check("nor is an unknown code", lab.reportable_subtest("nonsense"), None)
check("concepts resolve", lab.concept("951277"), "TB_LAM")

print("\nSummarising a mixed extract")
rows = [
    # A malaria smear contributes once, through Detection only.
    {"test_code": "372071003", "subtest_code": "01", "result": "MPS ++ SEEN"},
    {"test_code": "372071003", "subtest_code": "02", "result": "0"},
    {"test_code": "372071003", "subtest_code": "03", "result": "0"},
    {"test_code": "372071003", "subtest_code": "04", "result": "0"},
    {"test_code": "372071003", "subtest_code": "01", "result": "NO MPS SEEN"},
    # A full blood count contributes nothing at all.
    {"test_code": "26604007", "subtest_code": "2660400715", "result": "11.2"},
    {"test_code": "26604007", "subtest_code": "2660400701", "result": "7.8"},
    # HIV: Determine counts, the other assays and the blank final do not.
    {"test_code": "165813002", "subtest_code": "kizxvo8k", "result": "POSITIVE"},
    {"test_code": "165813002", "subtest_code": "uvoecxsw", "result": "0"},
    {"test_code": "165813002", "subtest_code": "z1o1wvbc", "result": "0"},
    {"test_code": "165813002", "subtest_code": "kizxvo8k", "result": "NEGATIVE"},
    # Xpert, both clauses present.
    {"test_code": "9000001", "subtest_code": "ma7dy01a",
     "result": "MTB DETECTED LOW,RIF resistance NOT DETECTED"},
    {"test_code": "9000001", "subtest_code": "tj6l4jhh", "result": "NOT DETECTED"},
]
s = lab.summarise(rows)
check("malaria: one positive, one negative",
      (s["MALARIA_MICROSCOPY"][P], s["MALARIA_MICROSCOPY"][N]), (1, 1))
check("a full blood count contributes no concept", "CBC" in s, False)
check("only the reportable analytes appear", sorted(s),
      ["HIV_SCREEN", "MALARIA_MICROSCOPY", "TB_XPERT"])
check("HIV: one positive, one negative",
      (s["HIV_SCREEN"][P], s["HIV_SCREEN"][N]), (1, 1))
check("Xpert counts the case once, from MTB alone",
      (s["TB_XPERT"][P], s["TB_XPERT"][N]), (1, 0))
check("subtest matching is case-insensitive",
      lab.summarise([{"test_code": "9000001", "subtest_code": "MA7DY01A",
                      "result": "MTB NOT DETECTED"}])["TB_XPERT"][N], 1)
check("empty input", lab.summarise([]), {})
check("None input", lab.summarise(None), {})

print()
if failures:
    print(f"{len(failures)} check(s) failed:\n")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
