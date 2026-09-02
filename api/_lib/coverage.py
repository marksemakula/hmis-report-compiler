"""Which cells on a form does this compiler answer for?

THE FINDING THIS MODULE EXISTS TO HANDLE

The request was to make every field carry a value, or a zero where nothing was
reported. Measured against the live national instance on 2 September 2026, that
cannot be done by sending zeros, because DHIS2 will not keep them:

    POST /api/dataValueSets?dryRun=true   value "1" -> imported=1
    POST /api/dataValueSets?dryRun=true   value "0" -> imported=0 ignored=0

The zero is not rejected, not ignored, not flagged as a conflict. It is dropped
in silence. The cause is `zeroIsSignificant`, which is false on 3,247 of the
3,252 data elements across the eight data sets - the five exceptions are all
cold-chain and condom counts on 105:02-03. Consistent with that, six
data-set/period combinations at this facility hold 2,038 stored values between
them and not one of them is a zero.

So on the DHIS2 side the absent cell *is* the zero, and an app that "filled
every field" would report six thousand values written while the server kept a
hundred. The zero belongs in our own rendering, where it can be seen and
checked, and nowhere else.

WHICH LEAVES THE REAL QUESTION

A zero is a claim. Printing 0 against "Cholera - Deaths" says we looked and
there were none. We may only make that claim for cells this compiler actually
computes. Everything else must stay visibly blank, because 105:01 alone carries
6,329 cells of which the OPD compiler answers for 4,060; the rest - nutrition,
rehabilitation, gender-based violence, cancer - are filled by other staff from
paper registers, and a zero of ours printed in their column is a lie about their
work.

Ownership is therefore derived from the compiler's own mapping tables rather
than declared by hand, so that extending a mapping extends the zero-fill and the
two can never drift apart.
"""
from .metadata import mapping


def _opd_owned() -> set:
    """Elements compile_opd can write: the two attendance elements, plus every
    coded element on the OPD age-and-sex disaggregation.

    That disaggregation is what separates the diagnosis grid from the rest of
    105:01, and it separates it cleanly: of the form's 623 elements, 406 carry
    it and they are exactly attendance plus the thirty condition groups.
    Elements on the *default* combination are writable by the compiler when a
    diagnosis maps to one, but they are not zero-filled - a blank there is a
    question we have not asked, not an answer of none."""
    m = mapping()
    des = m["dataElements"].get("HMIS105_01", {})
    target = m["categoryCombos"]["OPD_AGE_SEX"]["id"]
    owned = {deid for deid, info in des.items() if info.get("categoryCombo") == target}
    for key in ("OA01_newAttendance", "OA02_reAttendance"):
        de = m["keyDataElements"].get(key)
        if de:
            owned.add(de)
    return owned


def _ipd_owned() -> set:
    """Elements compile_ipd can write: the four ward-level indicators it derives,
    plus every Section-6 case and death element in the diagnosis index.

    CI01 (beds available) is deliberately absent. It is a facility declaration,
    not something a register can yield, and zero beds is not a thing to assert."""
    from .validators import ipd_diagnosis_index

    m = mapping()
    key = m["keyDataElements"]
    owned = {key[k] for k in ("CI02_admissions", "CI03_deaths", "CI04_patientDays",
                              "CI05_avgLengthOfStay") if k in key}
    for entry in ipd_diagnosis_index().values():
        for kind in ("cases", "deaths"):
            if entry.get(kind):
                owned.add(entry[kind])
    return owned


def _surv_owned() -> set:
    """Every 033B element the tally can address.

    033B is the one report where the zero carries the most weight: it is a
    weekly surveillance return, and "no cases of cholera this week" is the
    substance of the exercise, not an absence of data. All 239 elements sit on
    the default combination, one cell each."""
    idx = mapping().get("HMIS033B_codeIndex", {})
    return set(idx.values())


# A report absent from this table has no compiler, so it owns nothing and
# nothing on its form is zero-filled. That is the correct behaviour for the five
# reports still awaiting a compiler: their preview shows the blank official form.
_OWNERS = {
    "OPD": _opd_owned,
    "IPD": _ipd_owned,
    "SURV": _surv_owned,
}


def owned_elements(report_type: str) -> set:
    fn = _OWNERS.get((report_type or "").upper())
    if not fn:
        return set()
    try:
        return fn()
    except Exception:
        # Ownership is an aid to reading the form. If the metadata needed to
        # compute it is unavailable, the preview must still render - it simply
        # falls back to showing blanks, which understates rather than misleads.
        return set()


def dataset_cells(report_type: str) -> list:
    """Every (dataElement, categoryOptionCombo) pair the data set defines.

    This is the form's true denominator. It is built from the category
    combination attached to each element rather than from the rendered HTML, so
    it counts the cells DHIS2 would accept even where the Ministry's custom
    layout omits them."""
    m = mapping()
    entry = m.get("reportTypes", {}).get((report_type or "").upper())
    if not entry:
        return []
    des = m["dataElements"].get(entry["dataSet"], {})
    by_id = {cc["id"]: cc for cc in m["categoryCombos"].values()}
    out = []
    for deid, info in des.items():
        cc = by_id.get(info.get("categoryCombo"))
        if not cc:
            # A combination this build does not carry. One cell is the honest
            # floor: the element exists and takes at least one value.
            out.append((deid, None))
            continue
        for coc in cc["cocs"].values():
            out.append((deid, coc))
    return out


def zero_fill(values: list, report_type: str) -> tuple:
    """Add an explicit zero for every owned cell the compiler did not fill.

    Returns (values_for_display, summary). The zeros are marked `imputed` so
    that the renderer can show them differently and, more importantly, so that
    nothing downstream mistakes them for measurements. They are never added to
    the payload that goes to DHIS2 - see the module docstring for why that
    would be pointless as well as wrong."""
    owned = owned_elements(report_type)
    have = {(v.get("dataElement"), v.get("categoryOptionCombo")) for v in (values or [])}

    m = mapping()
    des = m["dataElements"].get(
        m.get("reportTypes", {}).get((report_type or "").upper(), {}).get("dataSet", ""), {})
    coc_names = {}
    for cc in m["categoryCombos"].values():
        for name, cid in cc["cocs"].items():
            coc_names[cid] = name

    zeros = []
    for de, coc in dataset_cells(report_type):
        if de not in owned or coc is None or (de, coc) in have:
            continue
        zeros.append({
            "dataElement": de,
            "dataElementName": des.get(de, {}).get("name", de),
            "categoryOptionCombo": coc,
            "categoryOptionComboName": coc_names.get(coc, coc),
            "value": "0",
            "imputed": True,
        })

    total_cells = len(dataset_cells(report_type))
    owned_cells = sum(1 for de, coc in dataset_cells(report_type)
                      if de in owned and coc is not None)
    return list(values or []) + zeros, {
        "cells": total_cells,
        "owned": owned_cells,
        "compiled": len(values or []),
        "zeroFilled": len(zeros),
        "notOurs": total_cells - owned_cells,
    }
