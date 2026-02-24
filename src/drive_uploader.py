"""
src/drive_uploader.py – Upload job application files to Google Drive.

Folder structure on Drive:
    Job Applications - Resumes/
        └── {Company}/
                ├── Zihan Wang-Resume-{Company}.pdf
                ├── Zihan Wang-CoverLetter-{Company}.txt
                └── Zihan Wang-Why{Company}.txt

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

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CREDS_FILE   = PROJECT_ROOT / "config" / "gdrive_credentials.json"
TOKEN_FILE   = PROJECT_ROOT / "config" / "gdrive_token.json"
SCOPES       = ["https://www.googleapis.com/auth/drive.file"]
ROOT_FOLDER  = "Job Applications - Resumes"

# MIME types
_MIME = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".html": "text/html",
}


def _get_service():
    """Authenticate and return a Google Drive API service client."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

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

    return build("drive", "v3", credentials=creds)


def _get_or_create_folder(service, name: str, parent_id: str | None = None) -> str:
    """Return a Drive folder ID, creating it if it doesn't exist."""
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"

    results = service.files().list(q=q, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    folder = service.files().create(body=meta, fields="id").execute()
    logger.info(f"  📁 Created Drive folder: {name}")
    return folder["id"]


def _upload_file(service, file_path: Path, folder_id: str) -> str:
    """Upload a single file to a Drive folder. Returns shareable URL."""
    from googleapiclient.http import MediaFileUpload

    mime = _MIME.get(file_path.suffix.lower(), "application/octet-stream")
    meta = {"name": file_path.name, "parents": [folder_id]}
    media = MediaFileUpload(str(file_path), mimetype=mime, resumable=False)
    uploaded = service.files().create(body=meta, media_body=media, fields="id").execute()
    file_id = uploaded["id"]

    # Anyone with the link can view
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"


def upload_job_files(
    company: str,
    pdf_path: Path | str | None = None,
    cover_letter: Path | str | None = None,
    why_company: Path | str | None = None,
    date_str: str | None = None,
) -> str | None:
    """
    Upload all job application files for a company to a date/company subfolder on Drive.

        Job Applications - Resumes/
            └── 2026-02-25/
                    └── Cognition/
                            ├── Resume.pdf
                            ├── CoverLetter.txt
                            └── WhyCompany.txt

    Returns the Drive shareable URL of the resume PDF (for Notion), or None on failure.
    """
    from datetime import date as _date
    today = date_str or _date.today().isoformat()

    files = {k: Path(v) for k, v in {
        "pdf":          pdf_path,
        "cover_letter": cover_letter,
        "why_company":  why_company,
    }.items() if v and Path(v).exists()}

    if not files:
        logger.warning(f"  Drive upload skipped — no files found for {company}")
        return None

    try:
        service = _get_service()

        # Root folder → date subfolder → company subfolder
        root_id    = _get_or_create_folder(service, ROOT_FOLDER)
        date_id    = _get_or_create_folder(service, today,    parent_id=root_id)
        company_id = _get_or_create_folder(service, company,  parent_id=date_id)

        pdf_url = None
        for key, path in files.items():
            url = _upload_file(service, path, company_id)
            logger.info(f"  ☁️  Drive [{company}/{path.name}] → {url}")
            if key == "pdf":
                pdf_url = url

        return pdf_url

    except Exception as e:
        logger.warning(f"  ❌ Drive upload failed [{company}]: {e}")
        return None


# ── One-time auth helper ────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("Authenticating with Google Drive...")
    svc = _get_service()
    root_id = _get_or_create_folder(svc, ROOT_FOLDER)
    print(f"✅ Auth successful! Root folder '{ROOT_FOLDER}' ready (id: {root_id})")
