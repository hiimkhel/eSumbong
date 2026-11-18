"""users.py
Purpose: Manage the accounts responders and the city desk sign in with.
Residents need no account.

IDs are made for you from the barangay's short code (config.BARANGAY_CODES):
    SR-T01, SR-T02, ...   San Roque's tanods, numbered in order
    SR-CAPT               San Roque's captain (one per barangay)
    city                  the city desk (config.DESK_ID)
Sign-in ignores case, so a tanod may type sr-t01.

Run from the repository folder (the broker may be running; changes apply at
the next sign-in):
    python users.py add --barangay san-roque --position tanod     # -> SR-T01, asks for a PIN
    python users.py add --barangay san-roque --position captain   # -> SR-CAPT
    python users.py add --id smoke-tanod --barangay san-roque     # a special account with your own ID
    python users.py reset-pin SR-T01
    python users.py remove SR-T01
    python users.py list                                          # or: list --barangay san-roque
    python users.py codes                                         # every barangay's code
    python users.py desk-password                                 # set the city desk password

PINs and passwords are typed at a hidden prompt (never on the command line,
so they stay out of shell history) and stored only as hashes (auth.py).
"""

import argparse
import datetime
import getpass
import re
import sys

import auth
import config
import store

POSITIONS = ("tanod", "captain")
TANOD_ID = re.compile(r"^([A-Z0-9]+)-T(\d+)$")
CAPTAIN_ID = re.compile(r"^([A-Z0-9]+)-CAPT$")
_CODE_TO_BARANGAY = {code: b for b, code in config.BARANGAY_CODES.items()}


# ---------------------------------------------------------------- IDs

def barangay_code(barangay):
    try:
        return config.BARANGAY_CODES[barangay]
    except KeyError:
        raise ValueError(f"{barangay} is not a barangay of {config.DISTRICT_NAME} "
                         "(see `python users.py codes`)") from None


def captain_id(barangay):
    return f"{barangay_code(barangay)}-CAPT"


def next_tanod_id(barangay):
    """SR-T01 for the first San Roque tanod, then one past the highest number
    in use (numbers are not reused while a higher one exists)."""
    code = barangay_code(barangay)
    numbers = [int(m.group(2)) for u in store.list_users(barangay)
               if (m := TANOD_ID.match(u["client_id"].upper())) and m.group(1) == code]
    return f"{code}-T{max(numbers, default=0) + 1:02d}"


def position_of(user):
    """'City desk', 'Tanod', 'Captain', or 'Responder' for a custom ID."""
    if user["role"] == "desk":
        return "City desk"
    cid = user["client_id"].upper()
    if TANOD_ID.match(cid):
        return "Tanod"
    if CAPTAIN_ID.match(cid):
        return "Captain"
    return "Responder"


def looks_generated(client_id):
    cid = client_id.upper()
    return any((m := pattern.match(cid)) and m.group(1) in _CODE_TO_BARANGAY
               for pattern in (TANOD_ID, CAPTAIN_ID))


# ---------------------------------------------------------------- commands

def ask_new_secret(label, role, ask=getpass.getpass):
    """Ask for a new PIN/password twice; return it, or raise ValueError."""
    secret = ask(f"{label}: ")
    problem = auth.secret_problem(role, secret)
    if problem:
        raise ValueError(problem)
    if ask(f"{label} again: ") != secret:
        raise ValueError("the two entries do not match")
    return secret


def add(barangay=None, position=None, client_id=None, ask=getpass.getpass):
    """Create a responder account and return a message naming its ID."""
    if barangay is not None:
        barangay_code(barangay)  # validates it
    if client_id is None:
        if position is None:
            raise ValueError("give --position tanod or --position captain (with --barangay), or --id")
        if barangay is None:
            raise ValueError(f"a {position} needs --barangay, e.g. --barangay san-roque")
        client_id = next_tanod_id(barangay) if position == "tanod" else captain_id(barangay)
    else:
        if position is not None:
            raise ValueError("use either --position (the ID is made for you) or --id, not both")
        if not client_id or " " in client_id or len(client_id) > 64 or not client_id.isprintable():
            raise ValueError("the ID must be one word of 1-64 characters")
        if client_id.lower() == config.DESK_ID:
            raise ValueError(f"{config.DESK_ID} is the city desk; use `desk-password`")
        if looks_generated(client_id):
            raise ValueError(f"IDs like {client_id} are made by --position; use that instead")
    existing = store.get_user(client_id)
    if existing:
        raise ValueError(f"{existing['client_id']} already exists; "
                         f"to change its PIN: python users.py reset-pin {existing['client_id']}")
    pin = ask_new_secret(f"New PIN for {client_id}", "responder", ask)
    store.save_user(client_id, "responder", auth.hash_secret(pin), barangay)
    where = config.BARANGAYS[barangay] if barangay else f"all of {config.DISTRICT_NAME}"
    return f"Added {client_id} ({position_of({'client_id': client_id, 'role': 'responder'}).lower()}, {where})."


def reset_pin(client_id, ask=getpass.getpass):
    user = store.get_user(client_id)
    if user is None:
        raise ValueError(f"no account {client_id} (see `python users.py list`)")
    if user["role"] == "desk":
        raise ValueError("that is the city desk; use `desk-password`")
    pin = ask_new_secret(f"New PIN for {user['client_id']}", "responder", ask)
    store.save_user(user["client_id"], "responder", auth.hash_secret(pin), user["barangay"])
    return f"Changed the PIN for {user['client_id']}."


def set_desk_password(ask=getpass.getpass):
    password = ask_new_secret("City desk password", "desk", ask)
    existing = store.get_user(config.DESK_ID)
    store.save_user(config.DESK_ID, "desk", auth.hash_secret(password))
    return f"{'Changed' if existing else 'Set'} the city desk password (ID {config.DESK_ID})."


def remove(client_id):
    removed = store.delete_user(client_id)
    if removed is None:
        raise ValueError(f"no account {client_id} (see `python users.py list`)")
    return (f"Removed {removed} and its subscriptions. It can no longer sign in "
            "(a session already open ends when it disconnects).")


def list_lines(barangay=None):
    if barangay is not None:
        barangay_code(barangay)
    users = store.list_users(barangay)
    if not users:
        where = f" in {config.BARANGAYS[barangay]}" if barangay else ""
        return [f"No accounts{where} yet. Add one with: "
                f"python users.py add --barangay {barangay or 'san-roque'} --position tanod"]
    rows = [("ID", "POSITION", "BARANGAY", "ADDED")]
    for u in users:
        where = ("-" if u["role"] == "desk"
                 else config.BARANGAYS.get(u["barangay"], f"All of {config.DISTRICT_NAME}"))
        added = datetime.datetime.fromtimestamp(u["created_at"]).strftime("%Y-%m-%d")
        rows.append((u["client_id"], position_of(u), where, added))
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    lines = [f"{a:<{widths[0]}}  {b:<{widths[1]}}  {c:<{widths[2]}}  {d}" for a, b, c, d in rows]
    lines.append(f"{len(users)} account{'s' if len(users) != 1 else ''}")
    return lines


def code_lines():
    width = max(len(n) for n in config.BARANGAYS.values())
    return [f"{config.BARANGAY_CODES[b]:<4} {name:<{width}}  ({b})" for b, name in config.BARANGAYS.items()]


# ---------------------------------------------------------------- CLI

def main(argv=None, ask=getpass.getpass):
    parser = argparse.ArgumentParser(
        description="eSumbong responder and city desk accounts",
        epilog="Example: python users.py add --barangay san-roque --position tanod")
    parser.add_argument("--db", default=config.DB_PATH, help="SQLite file (default: config.DB_PATH)")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    add_p = sub.add_parser("add", help="add a tanod or captain (the ID is made for you)")
    add_p.add_argument("--barangay", help="barangay topic level, e.g. san-roque (see `codes`)")
    add_p.add_argument("--position", choices=POSITIONS, help="tanod gets the next number (SR-T01), captain SR-CAPT")
    add_p.add_argument("--id", dest="client_id", help="a custom ID instead (e.g. a test account); "
                                                      "without --barangay it covers all of Jaro")
    reset_p = sub.add_parser("reset-pin", help="give an account a new PIN")
    reset_p.add_argument("client_id")
    rm_p = sub.add_parser("remove", help="delete an account and its subscriptions")
    rm_p.add_argument("client_id")
    list_p = sub.add_parser("list", help="list accounts")
    list_p.add_argument("--barangay", help="only this barangay's accounts")
    sub.add_parser("codes", help="show every barangay's short code")
    sub.add_parser("desk-password", help="set or change the city desk password")
    args = parser.parse_args(argv)

    if args.command == "codes":  # needs no database
        print("\n".join(code_lines()))
        return 0
    store.init_db(args.db)
    try:
        if args.command == "add":
            print(add(args.barangay, args.position, args.client_id, ask))
        elif args.command == "reset-pin":
            print(reset_pin(args.client_id, ask))
        elif args.command == "remove":
            print(remove(args.client_id))
        elif args.command == "list":
            print("\n".join(list_lines(args.barangay)))
        else:
            print(set_desk_password(ask))
    except ValueError as exc:
        print(f"! {exc}", file=sys.stderr)
        return 1
    finally:
        store.close_db()
    return 0


if __name__ == "__main__":
    sys.exit(main())
