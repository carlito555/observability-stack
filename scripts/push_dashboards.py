"""
push_dashboards.py — GitOps dashboard sync script.

Reads all *.json files from the DASHBOARDS_DIR directory and pushes them to
the target Grafana workspace using the Grafana HTTP API.  Called by the
GitHub Actions workflow after CloudFormation deployment succeeds.

Environment variables required:
  GRAFANA_URL      — e.g. https://<id>.grafana-workspace.us-east-1.amazonaws.com
  GRAFANA_API_KEY  — Grafana service-account token (stored in GitHub Secrets)
  DASHBOARDS_DIR   — relative path to the dashboards folder (default: dashboards)
"""

import json
import os
import sys
from pathlib import Path

import requests

GRAFANA_URL = os.environ["GRAFANA_URL"].rstrip("/")
GRAFANA_API_KEY = os.environ["GRAFANA_API_KEY"]
DASHBOARDS_DIR = Path(os.environ.get("DASHBOARDS_DIR", "dashboards"))

HEADERS = {
    "Authorization": f"Bearer {GRAFANA_API_KEY}",
    "Content-Type": "application/json",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def ensure_folder(folder_title: str) -> int:
    """Return uid for a Grafana folder, creating it if necessary."""
    resp = SESSION.get(f"{GRAFANA_URL}/api/folders")
    resp.raise_for_status()
    for folder in resp.json():
        if folder["title"] == folder_title:
            return folder["uid"]

    resp = SESSION.post(
        f"{GRAFANA_URL}/api/folders",
        json={"title": folder_title},
    )
    resp.raise_for_status()
    return resp.json()["uid"]


def push_dashboard(dashboard_path: Path, folder_uid: str) -> dict:
    """Upload or update a single dashboard JSON to Grafana."""
    with open(dashboard_path) as fh:
        dashboard = json.load(fh)

    # Strip server-assigned id/version so Grafana treats this as an upsert
    dashboard.pop("id", None)
    dashboard.pop("version", None)

    payload = {
        "dashboard": dashboard,
        "folderUid": folder_uid,
        "overwrite": True,
        "message": f"Deployed via GitHub Actions — {dashboard_path.name}",
    }

    resp = SESSION.post(f"{GRAFANA_URL}/api/dashboards/db", json=payload)
    resp.raise_for_status()
    return resp.json()


def main():
    if not DASHBOARDS_DIR.is_dir():
        print(f"[WARN] Dashboards directory '{DASHBOARDS_DIR}' not found — skipping.")
        sys.exit(0)

    dashboard_files = sorted(DASHBOARDS_DIR.glob("*.json"))
    if not dashboard_files:
        print("[INFO] No dashboard JSON files found — nothing to push.")
        sys.exit(0)

    print(f"[INFO] Found {len(dashboard_files)} dashboard(s) to push.")

    folder_uid = ensure_folder("GitOps — Automated")
    print(f"[INFO] Using folder uid: {folder_uid}")

    errors = []
    for path in dashboard_files:
        try:
            result = push_dashboard(path, folder_uid)
            print(f"  [OK]  {path.name} → {result.get('url', '')}")
        except requests.HTTPError as exc:
            print(f"  [ERR] {path.name}: {exc} — {exc.response.text[:200]}")
            errors.append(path.name)

    if errors:
        print(f"\n[FAIL] {len(errors)} dashboard(s) failed: {errors}")
        sys.exit(1)

    print(f"\n[DONE] {len(dashboard_files)} dashboard(s) pushed successfully.")


if __name__ == "__main__":
    main()
