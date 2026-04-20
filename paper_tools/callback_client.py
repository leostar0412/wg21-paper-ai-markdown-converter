"""Optional HTTP callback after workflow completion or validation failure."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


def post_callback(
    url: str,
    payload: dict[str, Any],
    *,
    auth_token: str | None = None,
    timeout_sec: float = 60.0,
) -> bool:
    """
    POST JSON to *url*. Returns True on 2xx.
    If *auth_token* is set, sends ``Authorization: Bearer <token>``.
    """
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    try:
        r = requests.post(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            timeout=timeout_sec,
        )
        if 200 <= r.status_code < 300:
            return True
        logger.warning("Callback HTTP %s: %s", r.status_code, r.text[:500])
        return False
    except Exception as e:
        logger.warning("Callback failed: %s", e)
        return False


def build_artifact_payload(
    *,
    run_status: str,
    workflow_run_url: str | None = None,
    artifact_name: str | None = None,
    artifact_id: int | None = None,
    artifact_archive_download_url: str | None = None,
    repository: str | None = None,
    run_id: str | None = None,
    papers: list[dict[str, Any]] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Professional callback body schema."""
    out: dict[str, Any] = {
        "schema_version": 1,
        "run_status": run_status,
    }
    if error_message:
        out["error_message"] = error_message
    if workflow_run_url:
        out["workflow_run_url"] = workflow_run_url
    if repository:
        out["repository"] = repository
    if run_id:
        out["run_id"] = run_id
    if artifact_name or artifact_id or artifact_archive_download_url:
        out["artifact"] = {}
        if artifact_name:
            out["artifact"]["name"] = artifact_name
        if artifact_id is not None:
            out["artifact"]["id"] = artifact_id
        if artifact_archive_download_url:
            out["artifact"]["archive_download_url"] = artifact_archive_download_url
    if papers is not None:
        out["papers"] = papers
    return out
