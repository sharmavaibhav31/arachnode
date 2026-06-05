"""
One-time migration: encrypt all existing plaintext URLs in the jobs table.

Usage:
    python scripts/migrate_encrypt_urls.py

Requires DATABASE_URL and ARACHNODE_ENCRYPTION_KEY env vars.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "aggregator-service"))

import asyncpg

import crypt


async def main():
    database_url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(database_url)

    rows = await conn.fetch("SELECT id, url FROM jobs WHERE url IS NOT NULL")
    total = len(rows)
    updated = 0

    for row in rows:
        encrypted = crypt.encrypt_url(row["url"])
        if encrypted != row["url"]:
            await conn.execute(
                "UPDATE jobs SET url = $1 WHERE id = $2", encrypted, row["id"]
            )
            updated += 1

    print(f"Migrated {updated}/{total} URLs.")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
