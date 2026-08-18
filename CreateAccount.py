"""Terminal utility — create Supabase Auth user, prompts email + password."""

from __future__ import annotations

import getpass
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    print("Hercules — Create Account")
    email = input("Email: ").strip()
    if not email:
        print("Error: email required", file=sys.stderr)
        sys.exit(1)

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Error: passwords do not match", file=sys.stderr)
        sys.exit(1)
    if len(password) < 8:
        print("Error: password must be at least 8 characters", file=sys.stderr)
        sys.exit(1)

    from SharedParams.Supabase import get_service_client

    client = get_service_client()

    try:
        resp = client.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
            }
        )
        print(f"Created: {resp.user.id} ({resp.user.email})")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
