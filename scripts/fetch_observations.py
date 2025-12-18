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


def get_random_observations(batch_size=1):
    """
    Fetches random research-grade Monarch observations without Life Stage annotation.
    Returns a list of observations.
    """
    params = {
        "taxon_id": MONARCH_TAXON_ID,
        "quality_grade": "research",
        "without_term_id": 1,  # Filter out observations with Life Stage annotation
        "photos": "true",
        "per_page": batch_size,
        "order_by": "observed_on",
        "order": "desc",
    }

    try:
        # First request to get total count
        response = requests.get(INAT_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        total_results = data['total_results']

        logger.info(f"Total available observations: {total_results}")

        # Limit offset to 9000 (iNat API has 10k limit)
        max_offset = min(total_results - batch_size, 9000)
        random_offset = random.randint(0, max(0, max_offset))

        # Fetch batch from random offset
        params["offset"] = random_offset
        response = requests.get(INAT_API_URL, params=params)
        response.raise_for_status()
        results = response.json().get('results', [])

        logger.info(f"Fetched {len(results)} observations from offset {random_offset}")
        return results

    except Exception as e:
        logger.error(f"Error fetching from iNaturalist: {e}")
        return []


def download_image(url, obs_id):
    """Downloads the image to local disk."""
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        filename = f"{obs_id}.jpg"
        filepath = IMAGE_DIR / filename

        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Downloaded image for observation {obs_id}")
        return filename
    except Exception as e:
        logger.error(f"Error downloading image {url}: {e}")
        return None


def process_observation(conn, obs):
    """Process a single observation: download image and save to database."""
    obs_id = obs['id']

    # Check if already processed
    if observation_exists(conn, obs_id):
        logger.info(f"Observation {obs_id} already exists in database, skipping")
        return False

    # Get photo URL
    photos = obs.get('photos', [])
    if not photos:
        logger.warning(f"Observation {obs_id} has no photos, skipping")
        return False

    # Use 'large' size for better quality
    photo_url = photos[0]['url'].replace('square', 'large')

    # Download image
    filename = download_image(photo_url, obs_id)
    if not filename:
        logger.error(f"Failed to download image for observation {obs_id}")
        return False

    # Save to database
    success = save_observation(conn, obs, filename)
    return success


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
        help='Maximum attempts to make (useful when many observations are already processed). Default: 3x the requested number'
    )

    args = parser.parse_args()

    batch_size = args.num
    max_attempts = args.max_attempts or (batch_size * 3)

    logger.info(f"Starting Monarch Observation Fetcher - requesting {batch_size} new observations")

    # Connect to database
    try:
        conn = get_db_connection()
        logger.info("Connected to PostgreSQL database")
    except Exception as e:
        logger.error(f"Cannot proceed without database connection: {e}")
        return

    processed_count = 0
    attempts = 0

    try:
        while processed_count < batch_size and attempts < max_attempts:
            # Fetch a batch of observations
            remaining = batch_size - processed_count
            fetch_size = min(remaining * 2, 200)  # Fetch extra to account for duplicates

            observations = get_random_observations(fetch_size)

            if not observations:
                logger.warning("No observations returned from iNaturalist")
                attempts += fetch_size
                continue

            # Process each observation
            for obs in observations:
                if processed_count >= batch_size:
                    break

                attempts += 1
                if process_observation(conn, obs):
                    processed_count += 1
                    logger.info(f"Progress: {processed_count}/{batch_size} observations processed")

                if attempts >= max_attempts:
                    logger.warning(f"Reached maximum attempts ({max_attempts})")
                    break

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
