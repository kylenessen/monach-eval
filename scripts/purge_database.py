#!/usr/bin/env python3
"""
Purge Database: Clear all observations and labels

WARNING: This will delete ALL data from observations and labels tables,
and remove all downloaded images.
Use this to start fresh.
"""

import os
import psycopg2
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database configuration
DB_CONFIG = {
    'dbname': os.getenv('POSTGRES_DB', 'postgres'),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'postgres'),
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432')
}

def main():
    print("⚠️  WARNING: This will delete ALL observations and labels data!")
    print("Type 'yes' to confirm: ", end='')

    # In Portainer console, we can't use input(), so check if running interactively
    import sys
    if sys.stdin.isatty():
        confirmation = input()
        if confirmation.lower() != 'yes':
            print("Aborted.")
            return 0
    else:
        print("(running non-interactively, proceeding...)")

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        print("\nDeleting all data from observations, labels, and Label Studio tasks...")

        # Delete in order (respecting foreign keys)
        cursor.execute("TRUNCATE TABLE labels CASCADE")
        cursor.execute("TRUNCATE TABLE observations CASCADE")

        # Also clear Label Studio tasks and annotations
        cursor.execute("TRUNCATE TABLE task_completion CASCADE")
        cursor.execute("TRUNCATE TABLE task CASCADE")

        conn.commit()

        print("✓ Database tables purged successfully")
        print("  - observations table: empty")
        print("  - labels table: empty")
        print("  - task table: empty")
        print("  - task_completion table: empty")

        cursor.close()
        conn.close()

        # Delete all images
        # Resolve paths relative to the project root
        project_root = Path(__file__).resolve().parent.parent
        image_dir = project_root / "data" / "images"
        print(f"\nDeleting images from {image_dir}...")
        if image_dir.exists():
            deleted_count = 0
            for image_file in image_dir.glob("*.jpg"):
                image_file.unlink()
                deleted_count += 1
            print(f"✓ Deleted {deleted_count} image files")
        else:
            print("  - No images directory found")

        print("\n✓ All data purged successfully!")
        print("\nYou can now:")
        print("  1. Run fetch_observations.py to fetch new observations")
        print("  2. Manually import images into Label Studio")

    except Exception as e:
        print(f"✗ Error: {e}")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())
