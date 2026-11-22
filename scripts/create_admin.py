"""Create the first admin of a live service (no demo accounts).

    python -m scripts.create_admin                      asks for name and email
    python -m scripts.create_admin --if-none            only if there is no active admin yet (used by start.bat)

Prints a temporary password once; it must be changed at the first login. The admin then creates the officer,
auditor and helper accounts on the Admin page (People)."""
import sys

from sqlalchemy import select

from app import accounts, audit
from app.db import SessionLocal
from app.models import Role, User

ROLES = [("citizen", "Citizen", "Files her own claim"), ("helper", "Helper", "Helps families who allow it"),
         ("officer", "Officer", "Decides claims sent to a person"), ("admin", "Admin", "Accounts, rules, API keys"),
         ("auditor", "Auditor", "Read-only: decisions, audit log, consents")]


def main():
    db = SessionLocal()
    for name, label, desc in ROLES:   # a fresh live database has no roles yet
        if db.get(Role, name) is None:
            db.add(Role(name=name, label=label, description=desc))
    db.commit()
    if "--if-none" in sys.argv and db.scalar(select(User.id).where(User.role == "admin", User.is_active.is_(True))):
        return
    print("\nCreate the first admin account for Aasra")
    name = input("Full name: ").strip()
    email = input("Email: ").strip()
    user, temp = accounts.create_staff(db, None, name, email, "admin")
    audit.record(db, "admin.first_admin_created", actor_role=audit.ACTOR_SYSTEM, details={"user_id": user.id}, commit=True)
    print(f"\nAdmin created: {user.email}\nTemporary password (shown once): {temp}\n"
          "Log in at /login (Staff sign-in) and choose a new password.\n")


if __name__ == "__main__":
    main()
