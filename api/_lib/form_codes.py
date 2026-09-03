"""The 325 data element codes on the CURRENT HMIS 105:01 form.

Read from the official DHIS2 custom form on 3 September 2026, as rendered by
this app's own preview endpoint, and enumerated here so an offline check can
answer one question: does this rule target a line the Ministry can actually
see?

That question needed asking. July 2026 was compiled with nine mappings aimed at
elements which are still attached to the data set but no longer appear on the
form - the 2019 physiotherapy section and four _2019 variants - so DHIS2 stored
1,174 conditions, 11.7 per cent of the month, where nobody would ever read
them. The import reported success every time.

To refresh after a form change: open /api/py/preview/OPD?period=<any> and read
the codes out of the rendered document. A code here that DHIS2 has dropped
shows up as a test failure, which is the point.
"""

def _r(prefix, n, start=1):
    return [f"{prefix}{i:02d}" for i in range(start, n + 1)]

FORM_CODES = (
    _r("CA", 27) + _r("CD", 19) + _r("CR", 3) + _r("CV", 7) + _r("DF", 22) +
    ["DT01"] + _r("EC", 25) + _r("EM", 3) + _r("EN", 17) +
    ["EP01", "EP01a", "EP01b", "EP01c", "EP01d", "EP01e"] + _r("EP", 18, 2) +
    _r("ES", 10) + ["ES10a", "ES10b", "ES10c"] +
    _r("IN", 6) + ["IN04a", "IN04b"] +
    _r("LD", 10) +
    _r("MC", 9) + ["MC11", "MC12", "MC13"] +
    _r("MH", 46) + _r("MN", 3) +
    ["NA01", "NA01a", "NA01b"] + _r("NA", 7, 2) +
    _r("NC", 6) + _r("ND", 7) + _r("NE", 15) + _r("NT", 6) +
    ["OA01", "OA02"] + _r("OD", 4) + ["OP01", "OR01", "OR02"] +
    _r("PC", 6) + _r("RD", 15) +
    ["TP01", "TP01a", "TP01b", "TP01c", "TP02", "TP02a", "TP02b", "TP02c",
     "TP03", "TP03a", "TP03b", "TP03c", "TP04"]
)

assert len(FORM_CODES) == len(set(FORM_CODES)) == 325, len(FORM_CODES)
