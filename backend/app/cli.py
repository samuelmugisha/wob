"""Administrative commands.

python -m app.cli create-user EMAIL "Display Name" ROLE   # prints a set-password link
python -m app.cli invite EMAIL                            # new link (signs the user out)
"""

import argparse
import hashlib
import sys
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.models import Role, User
from app.security import accounts
from app.services import storage


def _find(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(func.lower(User.email) == email.lower()))


def create_user(email: str, name: str, role: Role) -> None:
    settings = get_settings()
    with Session(get_engine()) as session:
        if _find(session, email):
            sys.exit(f"User {email} already exists; use `invite` for a new link.")
        user = User(email=email, display_name=name, role=role)
        session.add(user)
        session.flush()
        link = accounts.create_invite(session, user, None, settings)
        session.commit()
    print(f"Created {role.value} user {email}.")
    print(f"Set-password link (valid {settings.invite_ttl_hours} h, shown once):\n{link}")


def invite(email: str) -> None:
    settings = get_settings()
    with Session(get_engine()) as session:
        user = _find(session, email)
        if user is None or not user.is_active:
            sys.exit(f"No active user {email}.")
        user.password_hash = None
        user.mfa_enabled = False
        user.mfa_secret_encrypted = None
        accounts.revoke_all_sessions(session, user.id)
        link = accounts.create_invite(session, user, None, settings)
        session.commit()
    print(f"Set-password link for {email} (valid {settings.invite_ttl_hours} h):\n{link}")


def generate_file_key(key_id: str) -> None:
    print(
        "Add to FILE_ENCRYPTION_KEYS (keep every older key until rotation completes) and "
        "set FILE_ENCRYPTION_ACTIVE_KEY to the new id:"
    )
    print(f"{key_id}:{storage.generate_key()}")


def encrypt_storage() -> None:
    store = storage.build_storage(get_settings())
    changed = sum(store.encrypt_in_place(key) for key in store.keys())
    print(f"Encrypted {changed} plaintext file(s); others were already encrypted.")


def rotate_file_key() -> None:
    store = storage.build_storage(get_settings())
    changed = sum(store.rewrap(key) for key in store.keys())
    print(
        f"Re-wrapped {changed} file(s) to key {store.keyring.active!r}. Older keys can be "
        "removed from FILE_ENCRYPTION_KEYS once verify-storage passes."
    )


def verify_storage() -> None:
    """Decrypt every stored file and compare it with the SHA-256 recorded in the database."""
    store = storage.build_storage(get_settings())
    with Session(get_engine()) as session:
        expected = dict(
            session.execute(
                text(
                    "SELECT storage_key, sha256_hash FROM documents "
                    "UNION ALL SELECT storage_key, sha256_hash FROM reports "
                    "WHERE storage_key IS NOT NULL"
                )
            ).all()
        )
    problems = 0
    seen = set()
    for key in store.keys():
        seen.add(key)
        try:
            digest = hashlib.sha256(store.read(key)).hexdigest()
        except storage.StorageError as exc:
            problems += 1
            print(f"FAIL {key}: {exc}")
            continue
        if key not in expected:
            print(f"note {key}: not referenced in the database")
        elif digest != expected[key]:
            problems += 1
            print(f"FAIL {key}: SHA-256 differs from the database")
    for key in sorted(set(expected) - seen):
        problems += 1
        print(f"FAIL {key}: recorded in the database but missing from storage")
    print(f"Checked {len(seen)} file(s): {problems} problem(s).")
    sys.exit(1 if problems else 0)


def purge_expired() -> None:
    """Destroy the personal data of categories whose retention date has passed (s.18(4)).
    Schedule daily (cron or a systemd timer)."""
    from app.services.purge import purge_expired as run

    with Session(get_engine()) as session:
        results = run(session, storage.build_storage(get_settings()))
    if not results:
        print("Nothing past its retention date.")
    for category, counts in results.items():
        print(
            f"{category}: purged {counts.get('finalists', 0)} finalist(s), "
            f"{counts.get('files_shredded', 0)} file(s)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user")
    create.add_argument("email")
    create.add_argument("name")
    create.add_argument("role", choices=[r.value for r in Role])
    reinvite = commands.add_parser("invite")
    reinvite.add_argument("email")
    keygen = commands.add_parser("generate-file-key")
    keygen.add_argument("key_id", nargs="?", default=None)
    for name in ("encrypt-storage", "rotate-file-key", "verify-storage", "purge-expired"):
        commands.add_parser(name)
    args = parser.parse_args()
    if args.command == "create-user":
        create_user(args.email, args.name, Role(args.role))
    elif args.command == "invite":
        invite(args.email)
    elif args.command == "generate-file-key":
        generate_file_key(args.key_id or f"k{datetime.now(UTC):%Y%m%d}")
    elif args.command == "encrypt-storage":
        encrypt_storage()
    elif args.command == "rotate-file-key":
        rotate_file_key()
    elif args.command == "purge-expired":
        purge_expired()
    else:
        verify_storage()


if __name__ == "__main__":
    main()
