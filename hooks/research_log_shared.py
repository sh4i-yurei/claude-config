"""Shared by research-gate.py and research-log.py.

One copy of the domain logic, because the gate and the recorder must agree on
what counts as "the same site". If they disagreed, the gate would pace one
bucket while the recorder filled another, and neither would work.
"""

# Suffixes where the registered domain is three labels, not two. Not exhaustive —
# a full public suffix list is a dependency this does not need. Getting one wrong
# splits a site into two buckets, which errs toward pacing more, not less.
MULTI_LABEL_SUFFIXES = {
    "co.uk",
    "ac.uk",
    "org.uk",
    "gov.uk",
    "co.jp",
    "com.au",
    "co.nz",
    "com.br",
    "co.za",
    "com.cn",
}


def registered_domain(host: str) -> str:
    """Collapse a hostname to the thing politeness should be measured against.

    docs.github.com and github.com are one operator, and a crawler keyed on
    hostname would treat a thousand subdomains as a thousand separate sites.
    Production crawlers key on the registered domain for exactly this reason.
    """
    host = (host or "").lower().strip(".")
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if ".".join(parts[-2:]) in MULTI_LABEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])
