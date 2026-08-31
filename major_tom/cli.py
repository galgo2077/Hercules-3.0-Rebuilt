"""Command-line entrypoint for read-only Major Tom checks."""
import json
import sys

from .audit import audit
from .watchdog import watchdog


def main(argv=None):
    """Run audit or watchdog and print JSON; return non-zero on failure."""
    command = (argv or sys.argv[1:])[:1]
    result = audit() if command == ["audit"] else audit(deep=True) if command == ["deep-audit"] else watchdog() if command == ["watchdog"] else None
    if result is None:
        print("usage: python -m major_tom.cli [audit|deep-audit|watchdog]", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
