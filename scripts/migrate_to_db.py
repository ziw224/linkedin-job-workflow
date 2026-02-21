#!/usr/bin/env python3
"""
scripts/migrate_to_db.py — Migrate existing JSON-based user data to MySQL.

What it migrates:
  - config/users/{discord_id}/profile.json → users table
  - config/users/{discord_id}/seen_jobs.json → seen_jobs table (if exists)
  - data/seen_jobs.json → seen_jobs for the owner user (if OWNER_DISCORD_ID set)

Usage:
  cd ~/Projects/job-workflow-oss
  OWNER_DISCORD_ID=970771448320897095 python scripts/migrate_to_db.py
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

try:
    import db
except ImportError:
    print("❌ pymysql not installed. Run: pip install pymysql")
    sys.exit(1)

if not db.db_available():
    print("❌ Database not reachable. Check config.")
    sys.exit(1)

backend = "MySQL" if db._USE_MYSQL else f"SQLite ({db._SQLITE_PATH})"
print(f"✅ Connected to {backend}")

USERS_DIR = ROOT / "config" / "users"
owner_id  = os.getenv("OWNER_DISCORD_ID", "")
migrated_users = 0
migrated_seen  = 0

# ── Migrate per-user directories ───────────────────────────────────────────────
if USERS_DIR.exists():
    for user_dir in USERS_DIR.iterdir():
        if not user_dir.is_dir():
            continue
        discord_id = user_dir.name

        # profile.json → users table
        profile_path = user_dir / "profile.json"
        if profile_path.exists():
            with open(profile_path) as f:
                profile = json.load(f)
            # strip comment keys
            profile = {k: v for k, v in profile.items() if not k.startswith("_")}
            db.upsert_user(discord_id, **profile)
            print(f"  👤 Migrated user: {profile.get('name', discord_id)} ({discord_id})")
            migrated_users += 1

        # per-user seen_jobs.json → seen_jobs table
        seen_path = user_dir / "seen_jobs.json"
        if seen_path.exists():
            with open(seen_path) as f:
                data = json.load(f)
            ids = data.get("seen_ids", [])
            if ids:
                db.mark_jobs_seen(discord_id, ids)
                print(f"  📋 Migrated {len(ids)} seen jobs for {discord_id}")
                migrated_seen += len(ids)

# ── Migrate global seen_jobs.json for owner ────────────────────────────────────
global_seen = ROOT / "data" / "seen_jobs.json"
if global_seen.exists() and owner_id:
    with open(global_seen) as f:
        data = json.load(f)
    ids = data.get("seen_ids", [])
    if ids:
        db.mark_jobs_seen(owner_id, ids)
        print(f"  📋 Migrated {len(ids)} global seen jobs → user {owner_id}")
        migrated_seen += len(ids)
elif global_seen.exists() and not owner_id:
    print("⚠️  Found data/seen_jobs.json but OWNER_DISCORD_ID not set — skipping.")
    print("   Set OWNER_DISCORD_ID=<your_discord_id> to migrate global seen jobs.")

print(f"\n✅ Done — {migrated_users} users, {migrated_seen} seen job IDs migrated to MySQL")
