"""Shared settings. Change only with team agreement."""

HOST = "127.0.0.1"
PORT = 5050
DB_PATH = "sumbong.db"
ENCODING = "utf-8"
RETRY_SECONDS = 5
ESCALATE_SECONDS = 120              # demo: no response in 2 min (real world: about 30 min)
UNRESOLVED_ESCALATE_SECONDS = 180   # demo: not resolved 3 min after filing (real world: about 24 h)
ESCALATION_CHECK_SECONDS = 10
RESOLVED_HIDE_SECONDS = 600         # demo: HISTORY skips reports closed 10 min ago (real world: about 7 days)
CATEGORIES = ("noise", "drinking", "fight", "suspicious", "animals", "fire", "flood", "road")
URGENT_CATEGORIES = ("fire", "fight", "flood")
ROLES = ("resident", "responder", "desk")

# Sign-in (auth.py). Residents use an ID only. Responders sign in with an ID and
# a PIN, the single city desk with a password only; accounts are made with users.py.
DESK_ID = "city"
MIN_PIN_LENGTH = 4
MIN_DESK_PASSWORD_LENGTH = 8
MAX_FAILED_LOGINS = 5   # refused sign-ins for one ID before it is locked
LOCKOUT_SECONDS = 300   # how long the lock lasts

# Scope: the 42 barangays of Jaro district, Iloilo City. Topic level -> name.
# Source: https://en.wikipedia.org/wiki/Jaro,_Iloilo_City
CITY = "iloilo"
CITY_NAME = "Iloilo City"
DISTRICT_NAME = "Jaro"
BARANGAYS = {
    "arguelles": "Arguelles",
    "balabago": "Balabago",
    "balantang": "Balantang",
    "benedicto": "Benedicto",
    "bito-on": "Bito-on",
    "buhang": "Buhang",
    "buntatala": "Buntatala",
    "calubihan": "Calubihan",
    "camalig": "Camalig",
    "claudio-castilla-el-98": "Claudio Castilla El-98",
    "cuartero": "Cuartero",
    "cubay": "Cubay",
    "democracia": "Democracia",
    "desamparados": "Desamparados",
    "dungon-a": "Dungon A",
    "dungon-b": "Dungon B",
    "fajardo": "Fajardo",
    "javellana": "Javellana",
    "lanit": "Lanit",
    "libertad-santa-isabel": "Libertad Santa Isabel",
    "lopez-jaena": "Lopez Jaena",
    "luna": "Luna",
    "mh-del-pilar": "M.H. del Pilar",
    "mv-hechanova": "M.V. Hechanova",
    "ma-cristina": "Ma. Cristina",
    "montinola": "Montinola",
    "our-lady-of-fatima": "Our Lady of Fatima",
    "our-lady-of-lourdes": "Our Lady of Lourdes",
    "quintin-salas": "Quintin Salas",
    "sambag": "Sambag",
    "san-isidro": "San Isidro",
    "san-jose": "San Jose",
    "san-pedro": "San Pedro",
    "san-roque": "San Roque",
    "san-vicente": "San Vicente",
    "seminario": "Seminario",
    "simon-ledesma": "Simon Ledesma",
    "tabuc-suba": "Tabuc Suba",
    "tacas": "Tacas",
    "tagbac": "Tagbac",
    "taytay-zone-ii": "Taytay Zone II",
    "ungka": "Ungka",
}
# Short code per barangay for responder IDs made by users.py: SR-T01 is San Roque's
# first tanod, SR-CAPT its captain. Every code must be unique (tests/test_auth.py checks).
BARANGAY_CODES = {
    "arguelles": "ARG", "balabago": "BLB", "balantang": "BLT", "benedicto": "BEN",
    "bito-on": "BIT", "buhang": "BUH", "buntatala": "BUN", "calubihan": "CAL",
    "camalig": "CAM", "claudio-castilla-el-98": "CCE", "cuartero": "CUA", "cubay": "CUB",
    "democracia": "DEM", "desamparados": "DES", "dungon-a": "DGA", "dungon-b": "DGB",
    "fajardo": "FAJ", "javellana": "JAV", "lanit": "LAN", "libertad-santa-isabel": "LSI",
    "lopez-jaena": "LJ", "luna": "LUN", "mh-del-pilar": "MHP", "mv-hechanova": "MVH",
    "ma-cristina": "MAC", "montinola": "MON", "our-lady-of-fatima": "OLF",
    "our-lady-of-lourdes": "OLL", "quintin-salas": "QS", "sambag": "SAM",
    "san-isidro": "SI", "san-jose": "SJ", "san-pedro": "SP", "san-roque": "SR",
    "san-vicente": "SV", "seminario": "SEM", "simon-ledesma": "SL", "tabuc-suba": "TS",
    "tacas": "TAC", "tagbac": "TAG", "taytay-zone-ii": "TZ2", "ungka": "UNG",
}
REPORT_STATUSES =("RECEIVED", "RESPONDING", "RESOLVED", "WITHDRAWN")
CLOSED_STATUSES = ("RESOLVED", "WITHDRAWN")  # nothing more happens to these
DELIVERY_STATUSES = ("PENDING", "DELIVERED")
