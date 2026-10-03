"""One-time OAuth consent. Saves refresh token to DATA_DIR/token.json.

If the consent screen is in "Testing" status, Google expires the refresh
token after 7 days: publish the app or re-run this script.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def main():
    load_dotenv(BASE_DIR / ".env")
    client_file = os.environ.get("GOOGLE_OAUTH_CLIENT_FILE")
    if not client_file:
        raise SystemExit("GOOGLE_OAUTH_CLIENT_FILE is required")

    flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    token_path = DATA_DIR / "token.json"
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(creds.to_json())
    print(f"saved {token_path}")


if __name__ == "__main__":
    main()
