"""Runs the NocoBase sign-in API test without opening a browser."""

from ehrm.entrypoints.nocobase_login_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
