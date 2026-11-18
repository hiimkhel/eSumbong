"""auth.py
Purpose: Sign-in for responders and the city desk.

Who signs in how:
  * residents: an ID only (HELLO <id> resident), so reporting stays quick and
    anonymous reporting stays possible;
  * responders (tanods, captains): an ID and a PIN, given out by the captain
    with users.py; an account may be tied to one barangay, and then the broker
    only lets it subscribe to, update and post advisories for that barangay;
  * the city desk: one account, config.DESK_ID ("city"), with a password only.

Secrets are stored as salted PBKDF2-SHA256 hashes (standard library only) and
compared in constant time. A wrong ID, a wrong PIN and a wrong role all get the
same answer, so nobody can probe which accounts exist.

Guessing: after config.MAX_FAILED_LOGINS refused sign-ins for one ID, that ID
is locked for config.LOCKOUT_SECONDS, whether or not the account exists (so a
lock reveals nothing). The count lives in memory and resets when the broker
restarts or the right PIN is entered.
"""

import hashlib
import hmac
import secrets
import threading
import time

import config
import store

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000
LOGIN_FAILED = "sign-in failed: wrong ID, PIN or password"

_failures = {}  # client_id -> (failed attempts, time of the last one)
_failures_lock = threading.Lock()

# Checked against when the account does not exist, so a missing account takes
# as long to refuse as a wrong PIN.
_DUMMY_HASH = None


class AuthError(Exception):
    """A refused sign-in. The message is safe to send back as ERR."""


def hash_secret(secret, iterations=ITERATIONS):
    """'pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>' for a PIN or password."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_secret(secret, stored):
    """True if secret matches a hash_secret() result."""
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"),
                                     bytes.fromhex(salt), int(iterations))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)


def secret_problem(role, secret):
    """Why a new PIN or password is not acceptable, or None."""
    if role == "desk":
        if len(secret) < config.MIN_DESK_PASSWORD_LENGTH:
            return f"the desk password needs at least {config.MIN_DESK_PASSWORD_LENGTH} characters"
    elif len(secret) < config.MIN_PIN_LENGTH:
        return f"a PIN needs at least {config.MIN_PIN_LENGTH} characters"
    if not secret.isprintable() or " " in secret:
        return "use letters, digits or symbols, with no spaces"
    return None


def _locked_for(client_id, now):
    """Seconds left on this ID's lock, or 0."""
    with _failures_lock:
        count, last = _failures.get(client_id, (0, 0.0))
        if now - last >= config.LOCKOUT_SECONDS:
            _failures.pop(client_id, None)  # the lock (or the old failures) expired
            return 0
        return config.LOCKOUT_SECONDS - (now - last) if count >= config.MAX_FAILED_LOGINS else 0


def _record_failure(client_id, now):
    with _failures_lock:
        count, _ = _failures.get(client_id, (0, 0.0))
        _failures[client_id] = (count + 1, now)


def reset_failures():
    """Forget every failed attempt (tests, or an admin after a lockout)."""
    with _failures_lock:
        _failures.clear()


def check_login(client_id, role, secret, now=None):
    """The account dict for a valid responder/desk sign-in; raises AuthError.
    Residents need no account and get None."""
    global _DUMMY_HASH
    if role == "resident":
        return None
    if not secret:
        raise AuthError(f"{role}s must sign in with "
                        + ("the desk password" if role == "desk" else "their PIN"))
    now = time.time() if now is None else now
    left = _locked_for(client_id, now)
    if left:
        raise AuthError(f"too many failed sign-ins for {client_id[:64]}; "
                        f"try again in {max(1, round(left / 60))} min")
    user = store.get_user(client_id)
    if user is None:
        if _DUMMY_HASH is None:
            _DUMMY_HASH = hash_secret("not-a-real-secret")
        verify_secret(secret, _DUMMY_HASH)
        _record_failure(client_id, now)
        raise AuthError(LOGIN_FAILED)
    if not verify_secret(secret, user["secret_hash"]) or user["role"] != role:
        _record_failure(client_id, now)
        raise AuthError(LOGIN_FAILED)
    with _failures_lock:
        _failures.pop(client_id, None)
    return user
