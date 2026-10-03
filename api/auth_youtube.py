"""One-time OAuth consent. Saves refresh token to DATA_DIR/token.json."""
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
    token_path.write_text(creds.to_json())
    token_path.chmod(0o600)
    print(f"saved {token_path}")


if __name__ == "__main__":
    main()
