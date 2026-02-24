"""
src/drive_uploader.py – Upload resume PDFs to Google Drive and return shareable links.

Setup (one-time):
  1. Create a Google Cloud project, enable Google Drive API
  2. Create OAuth 2.0 Desktop credentials → download as config/gdrive_credentials.json
  3. Run: python3 src/drive_uploader.py   (opens browser once to authorize)
  4. Token saved to config/gdrive_token.json — all future runs are headless

Required files (gitignored):
    config/gdrive_credentials.json  – OAuth client secrets from Google Cloud Console
    config/gdrive_token.json        – saved access/refresh token (auto-created on first run)
"""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT  = Path(__file__).parent.parent.resolve()
CREDS_FILE    = PROJECT_ROOT / "config" / "gdrive_credentials.json"
TOKEN_FILE    = PROJECT_ROOT / "config" / "gdrive_token.json"
SCOPES        = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_NAME   = "Job Applications - Resumes"


def _get_service():
    """Authenticate and return a Google Drive API service client."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    # Refresh or re-authorize
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_FILE.exists():
                raise FileNotFoundError(
                    f"Google Drive credentials not found at {CREDS_FILE}.\n"
                    "Download OAuth 2.0 Desktop credentials from Google Cloud Console "
                    "and save as config/gdrive_credentials.json"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
        logger.info(f"Google Drive token saved → {TOKEN_FILE}")

    return build("drive", "v3", credentials=creds)


def _get_or_create_folder(service, folder_name: str) -> str:
    """Return the Drive folder ID, creating the folder if it doesn't exist."""
    # Search for existing folder
    query = (
        f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    # Create folder
    meta = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=meta, fields="id").execute()
    logger.info(f"Created Google Drive folder: {folder_name}")
    return folder["id"]


def upload_pdf(pdf_path: str | Path) -> str | None:
    """
    Upload a PDF to Google Drive and return a shareable HTTPS link.

    Returns the shareable URL string, or None on failure.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        logger.warning(f"  Drive upload skipped — file not found: {pdf_path}")
        return None

    try:
        from googleapiclient.http import MediaFileUpload

        service   = _get_service()
        folder_id = _get_or_create_folder(service, FOLDER_NAME)

        # Upload file
        file_meta = {"name": pdf_path.name, "parents": [folder_id]}
        media     = MediaFileUpload(str(pdf_path), mimetype="application/pdf", resumable=False)
        uploaded  = service.files().create(
            body=file_meta, media_body=media, fields="id"
        ).execute()
        file_id = uploaded["id"]

        # Make it accessible to anyone with the link
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        url = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
        logger.info(f"  ☁️  Uploaded to Drive: {pdf_path.name} → {url}")
        return url

    except Exception as e:
        logger.warning(f"  ❌ Drive upload failed [{pdf_path.name}]: {e}")
        return None


# ── One-time auth helper ────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("Authenticating with Google Drive...")
    svc = _get_service()
    folder_id = _get_or_create_folder(svc, FOLDER_NAME)
    print(f"✅ Auth successful! Drive folder '{FOLDER_NAME}' ready (id: {folder_id})")
