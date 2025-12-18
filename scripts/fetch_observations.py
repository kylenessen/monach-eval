#!/usr/bin/env python3
"""
Simplified Monarch Observation Fetcher

This script fetches random monarch butterfly observations from iNaturalist,
downloads their images, and stores metadata in PostgreSQL. No Label Studio integration.
"""

import os
import random
import requests
import logging
import argparse
import psycopg2
import psycopg2.extras
from pathlib import Path
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

# Load environment variables
load_dotenv()

# Configuration
INAT_API_URL = "https://api.inaturalist.org/v1/observations"
MONARCH_TAXON_ID = 48662
# Resolve paths relative to the project root (one level up from this script)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = PROJECT_ROOT / "data" / "images"

# Database configuration
DB_CONFIG = {
    'dbname': os.getenv('POSTGRES_DB', 'labelstudio'),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'postgres'),
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432')
}

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure directories exist
IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def get_db_connection():
    """Create and return a database connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


def observation_exists(conn, obs_id):
    """Check if an observation already exists in the database."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM observations WHERE observation_id = %s", (obs_id,))
        return cursor.fetchone() is not None


def save_observation(conn, obs_data, image_filename):
    """Save observation metadata to the database."""
    try:
        with conn.cursor() as cursor:
            # Extract relevant fields from iNaturalist observation
            location_parts = []
            if obs_data.get('place_guess'):
                location_parts.append(obs_data['place_guess'])
            location = ', '.join(location_parts) if location_parts else None

            cursor.execute("""
                INSERT INTO observations (
                    observation_id, inat_url, observed_on, observer_login, observer_name,
                    latitude, longitude, location, image_url, image_local_path,
                    quality_grade, num_identification_agreements, num_identification_disagreements,
                    license, raw_data
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (observation_id) DO NOTHING
            """, (
                obs_data['id'],
                obs_data.get('uri'),
                obs_data.get('observed_on'),
                obs_data.get('user', {}).get('login'),
                obs_data.get('user', {}).get('name'),
                obs_data.get('location', '').split(',')[0] if obs_data.get('location') else None,  # latitude
                obs_data.get('location', '').split(',')[1] if obs_data.get('location') and ',' in obs_data.get('location', '') else None,  # longitude
                location,
                obs_data.get('photos', [{}])[0].get('url') if obs_data.get('photos') else None,
                f"/data/images/{image_filename}",
                obs_data.get('quality_grade'),
                len([i for i in obs_data.get('identifications', []) if i.get('current', False) and i.get('category') == 'improving']),
                len([i for i in obs_data.get('identifications', []) if i.get('current', False) and i.get('category') == 'maverick']),
                obs_data.get('license_code'),
                psycopg2.extras.Json(obs_data)  # Store full API response as JSON
            ))
            conn.commit()
            logger.info(f"Saved observation {obs_data['id']} to database")
            return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to save observation {obs_data.get('id')}: {e}")
        return False


def fetch_candidates(target_count, existing_ids=set()):
    """
    Fetches a pool of candidate observations.
    Target pool size is 10x the requested count (or 200, whichever is larger).
    """
    pool_target = max(target_count * 10, 200)
    candidates = {}  # Use dict to deduplicate by ID {id: obs}
    
    # Get total count first
    try:
        params = {
            "taxon_id": MONARCH_TAXON_ID,
            "quality_grade": "research",
            "without_term_id": 1,
            "per_page": 1,
        }
        response = requests.get(INAT_API_URL, params=params)
        response.raise_for_status()
        total_results = response.json()['total_results']
        logger.info(f"Total available observations: {total_results}")
    except Exception as e:
        logger.error(f"Error fetching total count: {e}")
        return []

    # If total is small, just fetch everything sequentially
    if total_results <= pool_target:
        logger.info(f"Total results ({total_results}) is small. Fetching all available...")
        return fetch_all_available(total_results)

    # Otherwise, fetch from random offsets until we have enough
    attempts = 0
    max_attempts = 20  # Prevent infinite loops
    
    # Accessible limit is usually 10k for offset-based queries
    max_accessible = min(total_results, 10000)

    while len(candidates) < pool_target and attempts < max_attempts:
        attempts += 1
        
        # Pick a random offset
        # Ensure we don't go past the end
        page_size = 200
        max_start = max(0, max_accessible - page_size)
        offset = random.randint(0, max_start)
        
        logger.info(f"Fetching batch from offset {offset} (Pool size: {len(candidates)}/{pool_target})...")
        
        batch = fetch_batch(offset, page_size)
        if not batch:
            break
            
        for obs in batch:
            # Only add if not already in our pool AND not in DB (optimization)
            if obs['id'] not in candidates and obs['id'] not in existing_ids:
                candidates[obs['id']] = obs

    return list(candidates.values())

def fetch_batch(offset, limit=200):
    """Fetch a single batch of observations."""
    params = {
        "taxon_id": MONARCH_TAXON_ID,
        "quality_grade": "research",
        "without_term_id": 1,
        "photos": "true",
        "per_page": limit,
        "offset": offset,
        "order_by": "observed_on",
        "order": "desc",
    }
    try:
        response = requests.get(INAT_API_URL, params=params)
        response.raise_for_status()
        return response.json().get('results', [])
    except Exception as e:
        logger.error(f"Error fetching batch: {e}")
        return []

def fetch_all_available(total_limit):
    """Refetch logic for small result sets - sequential paging."""
    results = []
    page = 1
    per_page = 200
    while len(results) < total_limit:
        params = {
            "taxon_id": MONARCH_TAXON_ID,
            "quality_grade": "research",
            "without_term_id": 1,
            "photos": "true",
            "per_page": per_page,
            "page": page,
            "order_by": "observed_on",
            "order": "desc",
        }
        try:
            r = requests.get(INAT_API_URL, params=params)
            r.raise_for_status()
            batch = r.json().get('results', [])
            if not batch:
                break
            results.extend(batch)
            page += 1
        except Exception as e:
            logger.error(f"Error fetching page {page}: {e}")
            break
    return results

def get_existing_ids(conn):
    """Get set of all observation IDs currently in DB."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT observation_id FROM observations")
        return {row[0] for row in cursor.fetchall()}

def main():
    parser = argparse.ArgumentParser(
        description='Fetch random monarch butterfly observations from iNaturalist'
    )
    parser.add_argument(
        '-n', '--num',
        type=int,
        default=10,
        help='Number of observations to fetch (default: 10)'
    )
    parser.add_argument(
        '--max-attempts',
        type=int,
        default=None,
        help='Maximum attempts (unused in new logic)'
    )

    args = parser.parse_args()
    target_count = args.num

    logger.info(f"Starting Monarch Observation Fetcher - requesting {target_count} new observations")

    # Connect to database
    try:
        conn = get_db_connection()
        logger.info("Connected to PostgreSQL database")
    except Exception as e:
        logger.error(f"Cannot proceed without database connection: {e}")
        return

    try:
        # 1. Get existing IDs to avoid re-fetching known ones
        existing_ids = get_existing_ids(conn)
        logger.info(f"Database contains {len(existing_ids)} existing observations")

        # 2. Build Candidate Pool
        logger.info("Building candidate pool (10x target)...")
        candidates = fetch_candidates(target_count, existing_ids)
        logger.info(f"Collected {len(candidates)} candidates")

        # 3. Shuffle
        random.shuffle(candidates)

        # 4. Process until target reached
        processed_count = 0
        for obs in candidates:
            if processed_count >= target_count:
                break
            
            # Double check existence (redundant but safe)
            if obs['id'] in existing_ids:
                continue

            if process_observation(conn, obs):
                processed_count += 1
                logger.info(f"Progress: {processed_count}/{target_count} observations processed")
                existing_ids.add(obs['id'])

        logger.info(f"Completed: {processed_count} new observations added to database")

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        conn.close()
        logger.info("Database connection closed")


if __name__ == "__main__":
    main()
