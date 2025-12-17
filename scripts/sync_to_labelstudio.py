#!/usr/bin/env python3
"""
Sync Observations to Label Studio

This script reads observations from the PostgreSQL database and creates
corresponding tasks in Label Studio for annotation.
"""

import os
import requests
import logging
import argparse
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
LABEL_STUDIO_URL = os.getenv('LABEL_STUDIO_URL', 'http://localhost:8080')
LABEL_STUDIO_API_TOKEN = os.getenv('LABEL_STUDIO_API_TOKEN')
PROJECT_ID = os.getenv('LABEL_STUDIO_PROJECT_ID', '1')

# Database configuration
DB_CONFIG = {
    'dbname': os.getenv('POSTGRES_DB', 'postgres'),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'postgres'),
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432')
}

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_db_connection():
    """Create and return a database connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


def check_label_studio_connection():
    """Verify Label Studio is accessible and token is valid."""
    if not LABEL_STUDIO_API_TOKEN:
        return False, "No LABEL_STUDIO_API_TOKEN configured"

    try:
        headers = {"Authorization": f"Bearer {LABEL_STUDIO_API_TOKEN}"}
        response = requests.get(f"{LABEL_STUDIO_URL}/api/projects/{PROJECT_ID}", headers=headers, timeout=10)

        if response.status_code == 200:
            project_data = response.json()
            logger.info(f"Connected to Label Studio project: {project_data.get('title', PROJECT_ID)}")
            return True, project_data
        elif response.status_code == 401:
            return False, "API token invalid or expired"
        elif response.status_code == 404:
            return False, f"Project {PROJECT_ID} not found"
        else:
            return False, f"API returned {response.status_code}: {response.text[:200]}"

    except Exception as e:
        logger.error(f"Connection check failed: {e}")
        return False, str(e)


def get_observations_without_tasks(conn, limit=None):
    """
    Get observations from database that haven't been synced to Label Studio yet.
    This checks if the observation_id exists in Label Studio project tasks.
    """
    query = """
        SELECT
            observation_id,
            inat_url,
            observed_on,
            observer_login,
            location,
            image_local_path
        FROM observations
        ORDER BY created_at DESC
    """

    if limit:
        query += f" LIMIT {limit}"

    with conn.cursor() as cursor:
        cursor.execute(query)
        return cursor.fetchall()


def get_existing_task_ids(headers):
    """Get all existing task observation_ids from Label Studio to avoid duplicates."""
    try:
        # Get all tasks from the project
        response = requests.get(
            f"{LABEL_STUDIO_URL}/api/projects/{PROJECT_ID}/tasks",
            headers=headers,
            timeout=30
        )

        if response.status_code != 200:
            logger.warning(f"Could not fetch existing tasks: {response.status_code}")
            return set()

        tasks = response.json()
        # Extract observation_ids from task data
        existing_ids = set()
        for task in tasks:
            obs_id = task.get('data', {}).get('observation_id')
            if obs_id:
                existing_ids.add(str(obs_id))

        logger.info(f"Found {len(existing_ids)} existing tasks in Label Studio")
        return existing_ids

    except Exception as e:
        logger.error(f"Error fetching existing tasks: {e}")
        return set()


def create_label_studio_task(headers, observation):
    """Create a single task in Label Studio."""
    obs_id, inat_url, observed_on, observer_login, location, image_path = observation

    # Format date if it exists
    observed_on_str = observed_on.strftime('%Y-%m-%d') if observed_on else 'Unknown'

    # Create task data matching Label Studio's expected format
    task_data = {
        "data": {
            "image": image_path,  # Local path that Label Studio can serve
            "observation_id": str(obs_id),
            "inat_url": f'<a href="{inat_url}" target="_blank">View on iNaturalist</a>' if inat_url else 'N/A',
            "observed_on": observed_on_str,
            "observer": observer_login or 'Unknown',
            "location": location or 'Unknown'
        }
    }

    try:
        response = requests.post(
            f"{LABEL_STUDIO_URL}/api/projects/{PROJECT_ID}/import",
            headers=headers,
            json=[task_data],
            timeout=30
        )

        if response.status_code == 201:
            logger.info(f"✓ Created task for observation {obs_id}")
            return True
        else:
            logger.error(f"✗ Failed to create task for observation {obs_id}: {response.status_code} - {response.text[:200]}")
            return False

    except Exception as e:
        logger.error(f"✗ Error creating task for observation {obs_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Sync observations from database to Label Studio'
    )
    parser.add_argument(
        '-n', '--num',
        type=int,
        default=None,
        help='Number of observations to sync (default: all)'
    )
    parser.add_argument(
        '--skip-duplicates',
        action='store_true',
        help='Check for existing tasks and skip duplicates (slower but safer)'
    )

    args = parser.parse_args()

    logger.info("Starting Label Studio sync...")

    # Check Label Studio connection
    success, result = check_label_studio_connection()
    if not success:
        logger.error(f"Cannot connect to Label Studio: {result}")
        return

    headers = {
        "Authorization": f"Bearer {LABEL_STUDIO_API_TOKEN}",
        "Content-Type": "application/json"
    }

    # Get existing tasks if skip-duplicates is enabled
    existing_ids = set()
    if args.skip_duplicates:
        logger.info("Fetching existing tasks from Label Studio...")
        existing_ids = get_existing_task_ids(headers)

    # Connect to database
    try:
        conn = get_db_connection()
        logger.info("Connected to PostgreSQL database")
    except Exception as e:
        logger.error(f"Cannot proceed without database connection: {e}")
        return

    # Get observations
    observations = get_observations_without_tasks(conn, args.num)
    logger.info(f"Found {len(observations)} observations in database")

    if not observations:
        logger.info("No observations to sync")
        conn.close()
        return

    # Create tasks
    created_count = 0
    skipped_count = 0

    for obs in observations:
        obs_id = str(obs[0])

        # Skip if already exists in Label Studio
        if args.skip_duplicates and obs_id in existing_ids:
            logger.info(f"- Skipping observation {obs_id} (already exists)")
            skipped_count += 1
            continue

        if create_label_studio_task(headers, obs):
            created_count += 1

    conn.close()

    logger.info(f"\nSync completed!")
    logger.info(f"  Created: {created_count} tasks")
    if args.skip_duplicates:
        logger.info(f"  Skipped: {skipped_count} duplicates")
    logger.info(f"  Total observations processed: {len(observations)}")


if __name__ == "__main__":
    main()
