import os
import random
import time
import requests
import logging
from pathlib import Path
from dotenv import load_dotenv
import shutil

# Load environment variables
load_dotenv()

# Configuration
INAT_API_URL = "https://api.inaturalist.org/v1/observations"
MONARCH_TAXON_ID = 48662
PROJECT_ID = os.getenv("LABEL_STUDIO_PROJECT_ID", "1")
LS_URL = os.getenv("LABEL_STUDIO_URL", "http://localhost:8080")
IMAGE_DIR = Path("data/images")
PROCESSED_LOG = Path("data/processed_observations.txt")

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure directories exist
IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def load_processed_ids():
    """Load the set of already processed observation IDs."""
    if PROCESSED_LOG.is_dir():
        logger.warning(f"{PROCESSED_LOG} is a directory (Docker volume error). Removing it...")
        shutil.rmtree(PROCESSED_LOG)

    if not PROCESSED_LOG.exists():
        return set()
    with open(PROCESSED_LOG, "r") as f:
        return set(line.strip() for line in f)


def save_processed_id(obs_id):
    """Save a processed observation ID to the log file."""
    with open(PROCESSED_LOG, "a") as f:
        f.write(f"{obs_id}\n")


def get_random_observation():
    """Fetches a random research-grade Monarch observation without Life Stage annotation."""
    params = {
        "taxon_id": MONARCH_TAXON_ID,
        "quality_grade": "research",
        "without_term_id": 1,  # Filter out observations with Life Stage annotation
        "photos": "true",
        "per_page": 1,
    }

    try:
        response = requests.get(INAT_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        total_results = data['total_results']

        # Limit offset to 9000 (iNat API has 10k limit)
        max_offset = min(total_results, 9000)
        random_offset = random.randint(0, max_offset)

        params["offset"] = random_offset
        response = requests.get(INAT_API_URL, params=params)
        results = response.json().get('results', [])

        if not results:
            return None

        return results[0]

    except Exception as e:
        logger.error(f"Error fetching from iNat: {e}")
        return None


def download_image(url, obs_id):
    """Downloads the image to local disk."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()

        filename = f"{obs_id}.jpg"
        filepath = IMAGE_DIR / filename

        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return filename
    except Exception as e:
        logger.error(f"Error downloading image {url}: {e}")
        return None


def check_label_studio_connection():
    """Check if Label Studio is reachable and auth token is valid."""
    api_token = os.getenv("LABEL_STUDIO_API_TOKEN")

    if not api_token:
        return False, "No LABEL_STUDIO_API_TOKEN configured"

    try:
        # Check server health
        response = requests.get(f"{LS_URL}/api/version", timeout=10)
        if response.status_code != 200:
            return False, f"Server returned {response.status_code}"

        # Use Bearer format as per Label Studio documentation
        headers = {"Authorization": f"Bearer {api_token}"}
        response = requests.get(f"{LS_URL}/api/projects/{PROJECT_ID}", headers=headers, timeout=10)

        if response.status_code == 200:
            project_data = response.json()
            logger.info(f"Connected to project: {project_data.get('title', PROJECT_ID)}")
            return True, "Connected successfully"
        elif response.status_code == 401:
            return False, "API token invalid or expired"
        elif response.status_code == 404:
            return False, f"Project {PROJECT_ID} not found"
        else:
            return False, f"API returned {response.status_code}: {response.text[:200]}"

    except requests.exceptions.ConnectionError:
        return False, "Cannot connect to Label Studio"
    except Exception as e:
        logger.error(f"Connection check failed: {type(e).__name__}: {e}")
        return False, str(e)[:200]


def sync_to_label_studio(filename, obs_id, obs_data):
    """Creates a task in Label Studio using the REST API."""
    api_token = os.getenv("LABEL_STUDIO_API_TOKEN")

    if not api_token:
        logger.warning("No LABEL_STUDIO_API_TOKEN configured. Skipping sync.")
        return False

    try:
        # Construct the local path that Label Studio container can access
        image_path = f"/data/images/{filename}"

        task_data = {
            "image": image_path,
            "observation_id": obs_id,
            "inat_url": obs_data.get('uri'),
            "observed_on": obs_data.get('observed_on'),
        }

        # Import task via REST API using Bearer auth as per docs
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            f"{LS_URL}/api/projects/{PROJECT_ID}/import",
            headers=headers,
            json=[task_data],
            timeout=30
        )

        if response.status_code == 201:
            logger.info(f"Successfully imported task {obs_id} to Project {PROJECT_ID}")
            return True
        else:
            logger.error(f"Failed to import task {obs_id}: {response.status_code} - {response.text[:200]}")
            return False

    except Exception as e:
        logger.error(f"Failed to sync task {obs_id}: {e}")
        return False


def wait_for_label_studio():
    """Waits for Label Studio to be ready."""
    logger.info(f"Waiting for Label Studio at {LS_URL}...")

    while True:
        success, message = check_label_studio_connection()

        if success:
            logger.info("Label Studio is ready!")
            return
        else:
            logger.warning(f"Connection check failed: {message}. Retrying in 5s...")

        time.sleep(5)


def main():
    logger.info("Starting Monarch Phenology Ingestion Pipeline...")
    wait_for_label_studio()
    processed = load_processed_ids()

    while True:
        obs = get_random_observation()
        if not obs:
            logger.warning("No observation found. Retrying...")
            time.sleep(2)
            continue

        obs_id = str(obs['id'])

        if obs_id in processed:
            logger.info(f"Skipping duplicate {obs_id}")
            continue

        photos = obs.get('photos', [])
        if not photos:
            continue

        photo_url = photos[0]['url'].replace('square', 'medium')

        logger.info(f"Processing Observation {obs_id}...")

        filename = download_image(photo_url, obs_id)
        if filename:
            if sync_to_label_studio(filename, obs_id, obs):
                save_processed_id(obs_id)

        time.sleep(2)


if __name__ == "__main__":
    main()
