"""Offline checks for the on-premise extraction agent.

Two things must hold or the connector is worse than useless:

  1. The agent's age banding must be identical to the server's. They are
     implemented separately - the agent cannot import the server package - so
     drift is possible and would silently misreport children.
  2. Compiling from agent strata must produce exactly what compiling the same
     visits from an upload produces. If the two paths disagree, the figures
     depend on how the data got in, which no one could defend to the Ministry.

Also checks that the ingestion refuses anything carrying patient-level data.

    python scripts/test_agent.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "api"))
sys.path.insert(0, os.path.join(HERE, "..", "agent"))

from _lib import metadata  # noqa: E402

# A fixture with real category combos (from CONSTANTS) and a few elements.
DES = {
    "de_malaria": {"name": "105-EP01c. Malaria (Confirmed)", "code": "EP01c",
                   "categoryCombo": "esaNB4G5AHs"},
    "de_epilepsy": {"name": "105-MH33. Epilepsy", "code": "MH33",
                    "categoryCombo": "esaNB4G5AHs"},
    "de_flat": {"name": "105-XX01. Something undisaggregated", "code": "XX01",
                "categoryCombo": "bjDvmb4bfuf"},
    # All others, the real HMIS 105 line unmapped conditions are tallied
    # against. Both paths must route to it identically, or one silently
    # discards conditions the other counts.
    "de_other": {"name": "105-OP01. All others", "code": "OP01",
                 "categoryCombo": "esaNB4G5AHs"},
    # The two attendance elements the compiler always writes, under their real
    # identifiers, so _to_values can resolve their names.
    "sv6SeKroHPV": {"name": "105-OA01. New attendance", "code": "OA01",
                    "categoryCombo": "esaNB4G5AHs"},
    "sQ4EexvvhVe": {"name": "105-OA02. Re-attendance", "code": "OA02",
                    "categoryCombo": "esaNB4G5AHs"},
}
metadata._MAPPING = {
    **metadata.CONSTANTS,
    "dataElements": {"HMIS105_01": DES, "HMIS108": {}, "HMIS033B": {}},
    "HMIS105_01_codeIndex": metadata._build_code_index(DES),
    "HMIS108_codeIndex": {},
    "HMIS033B_codeIndex": {},
}

from _lib import agent as agentlib          # noqa: E402
from _lib import compiler as srv            # noqa: E402
import jrrh_agent as ag                     # noqa: E402
import queries                              # noqa: E402

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}\n     expected: {want!r}\n     actual:   {got!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


print("\nAge banding must be identical in the agent and the server")
ages = [0, 1 / 365, 27 / 365, 28 / 365, 28.9 / 365, 29 / 365, 0.5, 1, 4.99, 5,
        5.5, 9.99, 10, 15, 19.99, 20, 20.01, 45, 80, 130]
mismatch = [a for a in ages if ag.opd_band(a) != srv.opd_band(a)]
check(f"{len(ages)} ages band identically", mismatch, [])
check("newborn", ag.opd_band(0), "0-28Dys")
check("exactly 28 days", ag.opd_band(28 / 365), "0-28Dys")
check("29 days", ag.opd_band(29 / 365), "29Dys-4Yrs")
check("exactly 5 years", ag.opd_band(5.0), "5-9Yrs")
check("exactly 20 years", ag.opd_band(20.0), "20+Yrs")
check("agent band list matches server", ag.OPD_BANDS, srv.OPD_BANDS)

print("\nVisit categories")
check("Consultation is new", ag.visit_type("Consultation"), "New")
check("Follow up is a re-attendance", ag.visit_type("Follow up"), "Re")
check("RTT is a re-attendance", ag.visit_type("RTT - Return To Treatment"), "Re")
check("case and spacing tolerated", ag.visit_type("  FOLLOW UP "), "Re")
check("blank defaults to new", ag.visit_type(""), "New")
check("sex normalises", [ag.normalise_sex(x) for x in ["F", "female", "M", "Male", "?"]],
      ["Female", "Female", "Male", "Male", None])

print("\nThe two compile paths must agree exactly")
# Fifty visits spread across bands, sexes, visit types and diagnoses.
# The two paths speak different diagnosis namespaces and that is deliberate:
# an upload carries HMIS codes or free text a records officer wrote, while the
# agent carries ClinicMaster's ICD-11 stems. They collide - ICD-11 CA02 is acute
# pharyngitis, HMIS CA02 is prostate cancer - so the fixture pairs each HMIS
# code with a real ICD-11 code that maps to it, rather than pretending one
# string can mean both.
#
# ICD-11 codes taken from api/_lib/icd11_hmis_map.json, generated from Jinja's
# own Diseases table: 1F40 is falciparum malaria, 8A60 is epilepsy.
#
# This fixture first used 1C61, which the table did then map to malaria. It is
# not malaria: it is "HIV disease clinical stage 1 associated with malaria", and
# it was being classified by the co-morbidity named in passing rather than by
# its subject. Widening the HIV policy rule removed it from the malaria mapping
# and broke this test, which is the test doing its job.
DIAGNOSIS_PAIRS = [
    ("EP01c", "1F40"),      # malaria due to Plasmodium falciparum
    ("MH33", "8A60"),       # epilepsy
    ("QQ99", "ZZ99"),       # neither side maps: both must reach All others
]
VISITS = []
for i in range(50):
    VISITS.append({
        "in_period": True,
        "age_years": [0.01, 2.0, 7.0, 15.0, 40.0][i % 5],
        "sex": ["Male", "Female"][i % 2],
        "visit_type": ["New", "Re"][i % 3 == 0],
        "diagnosis_code": DIAGNOSIS_PAIRS[i % 3][0],
    })
upload_values, upload_unmapped = srv.compile_opd(VISITS, "202606")

# Fold the same visits into strata exactly as the extract does: an attendance
# row per stratum (one per visit) AND a condition row per diagnosis. Keeping
# them separate is what stops a visit with three conditions from counting as
# three attendances.
att, cond = {}, {}
for v in VISITS:
    b, sx, vt = srv.opd_band(v["age_years"]), v["sex"], v["visit_type"]
    att[(b, sx, vt)] = att.get((b, sx, vt), 0) + 1
    icd = next(icd for hmis, icd in DIAGNOSIS_PAIRS if hmis == v["diagnosis_code"])
    key = (icd, b, sx, vt)
    cond[key] = cond.get(key, 0) + 1
strata = ([{"diagnosis": agentlib.ATTENDANCE_SENTINEL, "band": b, "sex": s, "visit": vt, "n": n}
           for (b, s, vt), n in sorted(att.items())]
          + [{"diagnosis": d, "band": b, "sex": s, "visit": vt, "n": n}
             for (d, b, s, vt), n in sorted(cond.items())])
rows = agentlib.strata_to_rows(agentlib.validate_strata(strata))
agent_values, agent_unmapped = srv.compile_opd_strata(rows, "202606")


def as_dict(values):
    return {(v["dataElement"], v["categoryOptionCombo"]): v["value"] for v in values}


check("attendance strata reconstruct the visit count",
      sum(r["n"] for r in strata if r["diagnosis"] == agentlib.ATTENDANCE_SENTINEL),
      len(VISITS))
check("attendance rows are marked, condition rows are not",
      sorted({r["count_attendance"] for r in rows}), [False, True])
check("same number of data values", len(agent_values), len(upload_values))
check("every value identical", as_dict(agent_values), as_dict(upload_values))
# The unmapped LISTS name different strings - the upload reports the HMIS code
# it could not place, the agent reports the ICD-11 code - but the number of
# records that failed to map must be identical, or one path is silently
# discarding conditions the other counts.
check("the same number of records fail to map",
      sum(u["records"] for u in agent_unmapped),
      sum(u["records"] for u in upload_unmapped))
check("total attendance preserved",
      sum(int(v["value"]) for v in agent_values
          if v["dataElement"] in (metadata.CONSTANTS["keyDataElements"]["OA01_newAttendance"],
                                  metadata.CONSTANTS["keyDataElements"]["OA02_reAttendance"])),
      len(VISITS))

print("\nIngestion must refuse patient-level data")
for bad, why in [
    ([{"diagnosis": "x", "band": "20+Yrs", "sex": "Male", "visit": "New", "n": 1,
       "PatientNo": "JRRH/001"}], "PatientNo"),
    ([{"diagnosis": "x", "band": "20+Yrs", "sex": "Male", "visit": "New", "n": 1,
       "birthdate": "1990-01-01"}], "birthdate"),
    ([{"diagnosis": "x", "band": "20+Yrs", "sex": "Male", "visit": "New", "n": 1,
       "VisitNo": "V123"}], "VisitNo"),
]:
    try:
        agentlib.validate_strata(bad)
        check(f"rejects {why}", "accepted", "rejected")
    except ValueError as exc:
        check(f"rejects {why}", "patient-identifying" in str(exc), True)

print("\nOther ingestion guards")
def rejects(payload, fragment):
    try:
        agentlib.validate_strata(payload)
        return False
    except ValueError as exc:
        return fragment in str(exc)

base = {"diagnosis": "x", "band": "20+Yrs", "sex": "Male", "visit": "New", "n": 1}
check("unknown field", rejects([{**base, "extra": 1}], "unexpected field"), True)
check("bad age band", rejects([{**base, "band": "21-30Yrs"}], "age band"), True)
check("bad sex", rejects([{**base, "sex": "Other"}], "unrecognised sex"), True)
check("bad visit type", rejects([{**base, "visit": "Walkin"}], "visit type"), True)
check("negative count", rejects([{**base, "n": -1}], "negative"), True)
check("absurd count", rejects([{**base, "n": 99_000_000}], "maximum"), True)
check("missing diagnosis", rejects([{**base, "diagnosis": "  "}], "no diagnosis"), True)
check("not a list", rejects({"a": 1}, "must be a list"), True)
check("too many strata",
      rejects([base] * (agentlib.MAX_STRATA + 1), "exceeds the maximum"), True)
check("zero counts are dropped, not rejected",
      agentlib.validate_strata([{**base, "n": 0}, base]), [base])
check("sex and visit are normalised on the way in",
      agentlib.validate_strata([{**base, "sex": "f", "visit": "re-attendance"}]),
      [{**base, "sex": "Female", "visit": "Re"}])

print("\nSummary arithmetic")
s = agentlib.summarise(agentlib.validate_strata(strata))
check("visits summed", s["visits"], len(VISITS))
check("new plus re equals total", s["new"] + s["re"], s["visits"])
check("distinct diagnoses, sentinel excluded", s["diagnoses"], 3)
check("conditions counted separately from visits", s["conditions"], len(VISITS))

print("\nA visit with several conditions is still one attendance")
multi = agentlib.strata_to_rows(agentlib.validate_strata([
    {"diagnosis": agentlib.ATTENDANCE_SENTINEL, "band": "20+Yrs", "sex": "Male", "visit": "New", "n": 10},
    {"diagnosis": "EP01c", "band": "20+Yrs", "sex": "Male", "visit": "New", "n": 10},
    {"diagnosis": "MH26",  "band": "20+Yrs", "sex": "Male", "visit": "New", "n": 7},
    {"diagnosis": "XX01",  "band": "20+Yrs", "sex": "Male", "visit": "New", "n": 4},
]))
vals, _ = srv.compile_opd_strata(multi, "202606")
att_total = sum(int(v["value"]) for v in vals
                if v["dataElement"] == metadata.CONSTANTS["keyDataElements"]["OA01_newAttendance"])
cond_total = sum(int(v["value"]) for v in vals
                 if v["dataElement"] != metadata.CONSTANTS["keyDataElements"]["OA01_newAttendance"])
check("10 visits, 21 conditions -> attendance stays 10", att_total, 10)
check("...and the conditions all count", cond_total, 21)

print("\nQueries must be read-only")
for sql, ok in [
    (queries.OPD_ATTENDANCE, True),
    (queries.SCHEMA_PROBE, True),
    (queries.opd_diagnosis_sql(), True),
    ("DELETE FROM Visits", False),
    ("SELECT 1; DROP TABLE Patients", False),
    ("UPDATE Patients SET LastName='x'", False),
    ("EXEC sp_who", False),
]:
    try:
        queries.check_read_only(sql, "t")
        got = True
    except RuntimeError:
        got = False
    check(f"read-only guard: {sql.strip().splitlines()[0][:38]}", got, ok)

print("\nAgent authentication")
os.environ["AGENT_KEY"] = "k" * 32
check("correct key accepted", agentlib.require_agent("Bearer " + "k" * 32), True)
for bad in ["", "Bearer wrong", "wrong", "bearer " + "k" * 31, "Basic " + "k" * 32]:
    try:
        agentlib.require_agent(bad)
        check(f"rejects {bad[:18]!r}", "accepted", "rejected")
    except Exception as exc:
        check(f"rejects {bad[:18]!r}", getattr(exc, "status_code", None), 401)
check("fingerprint is short and stable",
      (len(agentlib.fingerprint("abc")), agentlib.fingerprint("abc") == agentlib.fingerprint("abc")),
      (12, True))
check("fingerprint does not leak the key",
      "k" * 32 in agentlib.fingerprint("k" * 32), False)
os.environ["AGENT_KEY"] = "short"
try:
    agentlib.agent_key()
    check("short key refused", "accepted", "rejected")
except Exception as exc:
    check("short key refused", getattr(exc, "status_code", None), 503)

print()
if failures:
    print(f"{len(failures)} check(s) failed:\n")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("All checks passed.")
