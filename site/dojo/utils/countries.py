import re

from babel import Locale

# CLDR also names non-places (EU, UN, Outlying Oceania, Unknown Region, the XA/XB pseudo-locales)
NON_COUNTRY_TERRITORIES = {"EU", "UN", "QO", "ZZ", "XA", "XB"}

COUNTRIES = dict(sorted(
    ((code, name) for code, name in Locale("en").territories.items()
     if re.fullmatch(r"[A-Z]{2}", code) and code not in NON_COUNTRY_TERRITORIES),
    key=lambda item: item[1],
))

lookup_country_code = COUNTRIES.get
