"""users.py
Purpose: Manage the accounts responders and the city desk sign in with.
Residents need no account.

Run from the repository folder (the broker may be running; changes apply at
the next sign-in):
    python users.py add tanod-a --barangay san-roque   # asks for the tanod's PIN
    python users.py add captain --barangay san-roque
    python users.py desk-password                       # set the city desk password
    python users.py list
    python users.py remove tanod-a
    python users.py add tanod-a --barangay san-roque    # again: resets the PIN

PINs and passwords are typed at a hidden prompt (never on the command line,
so they stay out of shell history) and stored only as hashes (auth.py).
"""

import argparse
import getpass
import sys

import auth
import config
import store


def ask_twice(label, role, ask=getpass.getpass):
    """Ask for a new PIN/password twice; return it, or raise ValueError."""
    secret = ask(f"{label}: ")
    problem = auth.secret_problem(role, secret)
    if problem:
        raise ValueError(problem)
    if ask(f"{label} again: ") != secret:
        raise ValueError("the two entries do not match")
    return secret


def add_responder(client_id, barangay, ask=getpass.getpass):
    if not client_id or " " in client_id or len(client_id) > 64 or not client_id.isprintable():
        raise ValueError("the ID must be one word of 1-64 characters")
    if client_id == config.DESK_ID:
        raise ValueError(f"{config.DESK_ID} is the city desk; use `desk-password`")
    if barangay is not None and barangay not in config.BARANGAYS:
        raise ValueError(f"{barangay} is not a barangay of {config.DISTRICT_NAME} (see config.BARANGAYS)")
    existing = store.get_user(client_id)
    if existing and existing["role"] != "responder":
        raise ValueError(f"{client_id} is a {existing['role']} account")
    pin = ask_twice(f"PIN for {client_id}", "responder", ask)
    store.save_user(client_id, "responder", auth.hash_secret(pin), barangay)
    where = config.BARANGAYS[barangay] if barangay else f"all of {config.DISTRICT_NAME}"
    return f"{'Updated' if existing else 'Added'} responder {client_id} ({where})."


def set_desk_password(ask=getpass.getpass):
    password = ask_twice("City desk password", "desk", ask)
    existing = store.get_user(config.DESK_ID)
    store.save_user(config.DESK_ID, "desk", auth.hash_secret(password))
    return f"{'Changed' if existing else 'Set'} the city desk password (ID {config.DESK_ID})."


def remove(client_id):
    if not store.delete_user(client_id):
        raise ValueError(f"no account {client_id}")
    return f"Removed {client_id}. They can no longer sign in (an open session ends when it disconnects)."


def list_lines():
    users = store.list_users()
    if not users:
        return ["No accounts yet. Add one with: python users.py add <id> --barangay <barangay>"]
    lines = [f"{'ID':<24} {'ROLE':<10} BARANGAY"]
    for u in users:
        where = "-" if u["role"] == "desk" else config.BARANGAYS.get(u["barangay"], f"all of {config.DISTRICT_NAME}")
        lines.append(f"{u['client_id']:<24} {u['role']:<10} {where}")
    return lines


def main(argv=None, ask=getpass.getpass):
    parser = argparse.ArgumentParser(description="eSumbong responder and city desk accounts")
    parser.add_argument("--db", default=config.DB_PATH, help="SQLite file (default: config.DB_PATH)")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="add a responder, or reset their PIN")
    add.add_argument("client_id")
    add.add_argument("--barangay", help="limit the account to one barangay (recommended), e.g. san-roque")
    sub.add_parser("desk-password", help="set or change the city desk password")
    rm = sub.add_parser("remove", help="delete an account")
    rm.add_argument("client_id")
    sub.add_parser("list", help="list accounts")
    args = parser.parse_args(argv)

    store.init_db(args.db)
    try:
        if args.command == "add":
            print(add_responder(args.client_id, args.barangay, ask))
        elif args.command == "desk-password":
            print(set_desk_password(ask))
        elif args.command == "remove":
            print(remove(args.client_id))
        else:
            print("\n".join(list_lines()))
    except ValueError as exc:
        print(f"! {exc}", file=sys.stderr)
        return 1
    finally:
        store.close_db()
    return 0


if __name__ == "__main__":
    sys.exit(main())
