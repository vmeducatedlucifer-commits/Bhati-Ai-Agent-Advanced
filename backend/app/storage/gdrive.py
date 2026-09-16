"""Google Drive Cloud Storage Sync for Workspaces and Code Projects.

Provides zero-data-loss workspace persistence on cloud hosts (like Render free tier)
by backing up workspace archives to a dedicated Google Drive folder using Service Account credentials.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("app.storage.gdrive")

# Ignore patterns for zip backups to keep archives small and ultra-fast
IGNORE_PATTERNS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git", "dist", ".vite",
    ".pytest_cache", ".next", ".cache", "*.pyc", "*.tsbuildinfo", "*.log"
}


class GoogleDriveManager:
    def __init__(self) -> None:
        self.enabled = False
        self.root_folder_id: str = ""

    def _get_credentials_dict(self) -> dict[str, Any] | None:
        raw = settings.GDRIVE_CREDENTIALS_JSON.strip()
        if not raw:
            return None

        # Check if it's base64 encoded
        if not raw.startswith("{"):
            try:
                raw = base64.b64decode(raw).decode("utf-8")
            except Exception:
                pass

        try:
            return json.loads(raw)
        except Exception as exc:
            log.error("Failed to parse GDRIVE_CREDENTIALS_JSON: %s", exc)
            return None

    def _build_service(self):
        """Constructs a thread-safe Google Drive API client."""
        creds_dict = self._get_credentials_dict()
        if not creds_dict:
            return None
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        scopes = ["https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def _init_sync(self) -> bool:
        creds_dict = self._get_credentials_dict()
        if not creds_dict:
            log.info("Google Drive storage disabled (no GDRIVE_CREDENTIALS_JSON provided).")
            return False

        try:
            # We don't save the service on 'self' to avoid multithreading SSL crashes!
            svc = self._build_service()
            if not svc:
                return False

            self.enabled = True
            # Ensure root folder exists
            self.root_folder_id = settings.GDRIVE_FOLDER_ID or self._get_or_create_root_folder_sync(svc)
            log.info("Google Drive storage enabled. Root folder ID: %s", self.root_folder_id)
            return True
        except Exception as exc:
            log.error("Failed to initialize Google Drive client: %s", exc)
            self.enabled = False
            return False

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _get_or_create_root_folder_sync(self, svc) -> str:
        folder_name = "Bhati_AI_Agent_Workspaces"
        try:
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = svc.files().list(q=query, fields="files(id, name)").execute()
            files = results.get("files", [])

            if files:
                return files[0]["id"]

            file_metadata = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
            }
            folder = svc.files().create(body=file_metadata, fields="id").execute()
            return folder.get("id", "")
        except Exception as exc:
            log.warning("Could not create/find root folder '%s': %s", folder_name, exc)
            return ""

    def _should_ignore(self, path: Path) -> bool:
        for part in path.parts:
            if part in IGNORE_PATTERNS:
                return True
            for pat in IGNORE_PATTERNS:
                if pat.startswith("*") and part.endswith(pat[1:]):
                    return True
        return False

    def _backup_workspace_sync(self, project_id: str, workspace_path: str, existing_file_id: str = "") -> str:
        if not self.enabled:
            return existing_file_id

        svc = self._build_service()
        if not svc:
            return existing_file_id

        ws_dir = Path(workspace_path)
        if not ws_dir.exists():
            return existing_file_id

        tmp_zip_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
                tmp_zip_path = tmp_zip.name

            file_count = 0
            with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(ws_dir):
                    dirs[:] = [d for d in dirs if not self._should_ignore(Path(root) / d)]
                    for file in files:
                        file_path = Path(root) / file
                        if not self._should_ignore(file_path):
                            arcname = file_path.relative_to(ws_dir)
                            zf.write(file_path, arcname)
                            file_count += 1

            if file_count == 0:
                return existing_file_id

            from googleapiclient.http import MediaFileUpload

            filename = f"workspace_{project_id}.zip"
            media = MediaFileUpload(tmp_zip_path, mimetype="application/zip", resumable=True)

            # Search if file already exists in Drive
            file_id = existing_file_id
            if not file_id:
                try:
                    q = f"name='{filename}' and trashed=false"
                    if self.root_folder_id:
                        q += f" and '{self.root_folder_id}' in parents"
                    results = svc.files().list(q=q, fields="files(id)").execute()
                    files = results.get("files", [])
                    if files:
                        file_id = files[0]["id"]
                except Exception:
                    pass

            if file_id:
                svc.files().update(fileId=file_id, media_body=media).execute()
                log.info("Updated Google Drive backup for project %s (%d files, fileId: %s)", project_id, file_count, file_id)
            else:
                file_metadata = {"name": filename}
                if self.root_folder_id:
                    file_metadata["parents"] = [self.root_folder_id]
                res = svc.files().create(body=file_metadata, media_body=media, fields="id").execute()
                file_id = res.get("id", "")
                log.info("Created Google Drive backup for project %s (%d files, fileId: %s)", project_id, file_count, file_id)

            return file_id
        except Exception as exc:
            log.error("Failed to backup workspace for project %s to Google Drive: %s", project_id, exc)
            return existing_file_id
        finally:
            if tmp_zip_path and os.path.exists(tmp_zip_path):
                try:
                    os.remove(tmp_zip_path)
                except Exception:
                    pass

    async def backup_workspace(self, project_id: str, workspace_path: str, existing_file_id: str = "") -> str:
        if not self.enabled:
            return existing_file_id
        return await asyncio.to_thread(self._backup_workspace_sync, project_id, workspace_path, existing_file_id)

    def _restore_workspace_sync(self, project_id: str, workspace_path: str, file_id: str = "") -> bool:
        if not self.enabled:
            return False

        svc = self._build_service()
        if not svc:
            return False

        ws_dir = Path(workspace_path)
        ws_dir.mkdir(parents=True, exist_ok=True)

        target_file_id = file_id
        filename = f"workspace_{project_id}.zip"

        if not target_file_id:
            try:
                q = f"name='{filename}' and trashed=false"
                if self.root_folder_id:
                    q += f" and '{self.root_folder_id}' in parents"
                results = svc.files().list(q=q, fields="files(id)").execute()
                files = results.get("files", [])
                if files:
                    target_file_id = files[0]["id"]
            except Exception as search_err:
                log.warning("Drive search failed for %s: %s", filename, search_err)

        if not target_file_id:
            log.info("No Google Drive backup found for project %s.", project_id)
            return False

        tmp_zip_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
                tmp_zip_path = tmp_zip.name

            from googleapiclient.http import MediaIoBaseDownload

            request = svc.files().get_media(fileId=target_file_id)
            with open(tmp_zip_path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

            with zipfile.ZipFile(tmp_zip_path, "r") as zf:
                resolved_ws = ws_dir.resolve()
                for member in zf.infolist():
                    member_path = (resolved_ws / member.filename).resolve()
                    if resolved_ws not in member_path.parents and member_path != resolved_ws:
                        log.warning("Skipping malicious zip entry %s escaping workspace %s", member.filename, resolved_ws)
                        continue
                    zf.extract(member, resolved_ws)

            log.info("Successfully restored workspace for project %s from Google Drive (fileId: %s)", project_id, target_file_id)
            return True
        except Exception as exc:
            log.error("Failed to restore workspace from Google Drive for project %s: %s", project_id, exc)
            return False
        finally:
            if tmp_zip_path and os.path.exists(tmp_zip_path):
                try:
                    os.remove(tmp_zip_path)
                except Exception:
                    pass

    async def restore_workspace(self, project_id: str, workspace_path: str, file_id: str = "") -> bool:
        if not self.enabled:
            return False
        return await asyncio.to_thread(self._restore_workspace_sync, project_id, workspace_path, file_id)


gdrive_manager = GoogleDriveManager()
