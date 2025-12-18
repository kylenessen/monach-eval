#!/usr/bin/env python3
"""
Database initialization script - runs automatically on container startup
"""
import os
import time
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

DB_CONFIG = {
    'dbname': os.getenv('POSTGRES_DB', 'postgres'),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'postgres'),
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432')
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS observations (
    observation_id BIGINT PRIMARY KEY,
    inat_url TEXT NOT NULL,
    observed_on DATE,
    observer_login TEXT,
    observer_name TEXT,
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    location TEXT,
    image_url TEXT,
    image_local_path TEXT,
    quality_grade TEXT,
    num_identification_agreements INTEGER,
    num_identification_disagreements INTEGER,
    license TEXT,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(observation_id)
);

CREATE TABLE IF NOT EXISTS labels (
    label_id SERIAL PRIMARY KEY,
    observation_id BIGINT NOT NULL,
    life_stage TEXT NOT NULL CHECK (life_stage IN ('Egg', 'Larva', 'Pupa', 'Adult', 'Unknown')),
    annotator TEXT,
    annotation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    label_studio_task_id INTEGER,
    label_studio_annotation_id INTEGER,
    FOREIGN KEY (observation_id) REFERENCES observations(observation_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_labels_observation_id ON labels(observation_id);
CREATE INDEX IF NOT EXISTS idx_labels_life_stage ON labels(life_stage);

CREATE OR REPLACE VIEW observations_with_labels AS
SELECT
    o.observation_id,
    o.inat_url,
    o.observed_on,
    o.observer_login,
    o.observer_name,
    o.latitude,
    o.longitude,
    o.location,
    o.image_url,
    o.image_local_path,
    o.quality_grade,
    l.life_stage,
    l.annotator,
    l.annotation_date,
    l.label_studio_task_id
FROM observations o
LEFT JOIN labels l ON o.observation_id = l.observation_id;
"""

def wait_for_db(max_attempts=30):
    """Wait for database to be ready"""
    for attempt in range(max_attempts):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            conn.close()
            print("✓ Database is ready")
            return True
        except psycopg2.OperationalError:
            if attempt < max_attempts - 1:
                print(f"Waiting for database... ({attempt + 1}/{max_attempts})")
                time.sleep(2)
            else:
                print("✗ Database not available after max attempts")
                return False
    return False

def init_schema():
    """Initialize database schema or migrate if needed"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        # Check if observations table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'observations'
            );
        """)
        exists = cursor.fetchone()[0]

        if not exists:
            print("Creating database schema...")
            cursor.execute(SCHEMA_SQL)
            print("✓ Database schema created successfully")
        else:
            print("✓ Observations table exists")
            
            # Check for raw_data column and add if missing
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='observations' AND column_name='raw_data';
            """)
            if not cursor.fetchone():
                print("Migrating schema: Adding raw_data column...")
                cursor.execute("ALTER TABLE observations ADD COLUMN raw_data JSONB;")
                print("✓ Added raw_data column")
            else:
                print("✓ Schema is up to date")

        cursor.close()
        conn.close()
        return True

    except Exception as e:
        print(f"✗ Error initializing database: {e}")
        return False

if __name__ == "__main__":
    print("Initializing database...")
    if wait_for_db():
        init_schema()
    else:
        print("Failed to connect to database")
        exit(1)
