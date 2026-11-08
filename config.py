"""Shared settings. Change only with team agreement."""

HOST = "127.0.0.1"
PORT = 5050
DB_PATH = "sumbong.db"
ENCODING = "utf-8"
RETRY_SECONDS = 5
ESCALATE_SECONDS = 120
ESCALATION_CHECK_SECONDS = 10
CATEGORIES = ("noise", "drinking", "fight", "suspicious", "animals", "fire", "flood", "road")
URGENT_CATEGORIES = ("fire", "fight", "flood")
ROLES = ("resident", "responder", "desk")
REPORT_STATUSES = ("RECEIVED", "RESPONDING", "RESOLVED")
DELIVERY_STATUSES = ("PENDING", "DELIVERED")
