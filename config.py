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
REPORT_STATUSES = ("RECEIVED", "RESPONDING", "RESOLVED", "WITHDRAWN")
CLOSED_STATUSES = ("RESOLVED", "WITHDRAWN")  # nothing more happens to these
DELIVERY_STATUSES = ("PENDING", "DELIVERED")
