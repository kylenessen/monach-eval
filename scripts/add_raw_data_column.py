#!/usr/bin/env python3
"""
Database Migration: Add raw_data column to observations table

Run this once to add the raw_data JSONB column to your existing database.
"""

import os
import psycopg2
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
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Check if column already exists
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'observations'
            AND column_name = 'raw_data'
        """)

        if cursor.fetchone():
            print("✓ Column 'raw_data' already exists in observations table")
        else:
            print("Adding 'raw_data' column to observations table...")
            cursor.execute("""
                ALTER TABLE observations
                ADD COLUMN raw_data JSONB
            """)
            conn.commit()
            print("✓ Successfully added 'raw_data' column")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"✗ Error: {e}")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())
