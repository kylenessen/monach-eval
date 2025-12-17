import os
import random
import time
import requests
import logging
from pathlib import Path
from dotenv import load_dotenv
from label_studio_sdk import Client
import shutil

# Load environment variables
load_dotenv()

# Configuration
INAT_API_URL = "https://api.inaturalist.org/v1/observations"
MONARCH_TAXON_ID = 48662
PROJECT_ID = os.getenv("LABEL_STUDIO_PROJECT_ID")
API_KEY = os.getenv("LABEL_STUDIO_API_KEY")
LS_USERNAME = os.getenv("LABEL_STUDIO_USERNAME")
LS_PASSWORD = os.getenv("LABEL_STUDIO_PASSWORD")
LS_URL = os.getenv("LABEL_STUDIO_URL", "http://localhost:8080")
IMAGE_DIR = Path("data/images")
PROCESSED_LOG = Path("data/processed_observations.txt")

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure directories exist
IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def load_processed_ids():
    if PROCESSED_LOG.is_dir():
        logger.warning(f"{PROCESSED_LOG} is a directory (Docker volume error). Removing it...")
        shutil.rmtree(PROCESSED_LOG)

    if not PROCESSED_LOG.exists():
        return set()
    with open(PROCESSED_LOG, "r") as f:
        return set(line.strip() for line in f)


def save_processed_id(obs_id):
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


def get_access_token_from_refresh(refresh_token):
    """Exchange a refresh token (PAT) for an access token."""
    try:
        logger.info(f"Exchanging refresh token for access token...")
        response = requests.post(
            f"{LS_URL}/api/token/refresh/",
            json={"refresh": refresh_token},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            access_token = data.get("access")
            if access_token:
                logger.info(f"Got access token: {access_token[:10]}...")
                return access_token
            else:
                logger.error(f"Refresh response missing access token: {data}")
                return None
        else:
            logger.error(f"Token refresh failed: {response.status_code} - {response.text[:200]}")
            return None

    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        return None


def get_working_api_key():
    """Get a working API key, trying multiple methods."""
    # If API_KEY looks like a JWT refresh token, exchange it for an access token
    if API_KEY and API_KEY.startswith("eyJ"):
        logger.info("API_KEY appears to be a JWT refresh token - exchanging for access token")
        access_token = get_access_token_from_refresh(API_KEY)
        if access_token:
            return access_token
        logger.warning("Token refresh failed, will try using refresh token directly")
        return API_KEY

    # Try provided API key as-is
    if API_KEY and API_KEY != "placeholder":
        logger.info("Using provided API_KEY")
        return API_KEY

    logger.error("No authentication credentials configured!")
    return None


def check_label_studio_connection():
    """Check if Label Studio is reachable and credentials are valid."""
    api_key = get_working_api_key()
    if not api_key:
        return False, "No credentials configured (need API_KEY or USERNAME+PASSWORD)"

    try:
        # First check if the server is up
        response = requests.get(f"{LS_URL}/api/version", timeout=10)
        if response.status_code != 200:
            return False, f"Server returned {response.status_code}"

        # Try using the SDK (it handles auth automatically)
        logger.info(f"Testing SDK auth with token: {api_key[:10]}...{api_key[-4:]}")
        ls = Client(url=LS_URL, api_key=api_key)

        # Test connection
        ls.check_connection()
        logger.info("SDK check_connection() passed")

        # Try to get the project
        project = ls.get_project(PROJECT_ID)
        logger.info(f"SDK successfully retrieved project: {project.title if hasattr(project, 'title') else PROJECT_ID}")

        return True, "Connected successfully with SDK"

    except requests.exceptions.ConnectionError:
        return False, "Cannot connect to Label Studio"
    except Exception as e:
        logger.error(f"SDK connection failed: {type(e).__name__}: {e}")
        return False, f"SDK auth failed: {str(e)[:200]}"


def sync_to_label_studio(filename, obs_id, obs_data):
    """Creates a task in Label Studio using the SDK."""
    api_key = get_working_api_key()
    if not api_key:
        logger.warning("Label Studio credentials not set. Skipping sync.")
        return False

    try:
        # Create SDK client
        ls = Client(url=LS_URL, api_key=api_key)
        project = ls.get_project(PROJECT_ID)

        # Construct the local path that Label Studio container can access
        image_path = f"/data/images/{filename}"

        task_data = {
            "image": image_path,
            "observation_id": obs_id,
            "inat_url": obs_data.get('uri'),
            "observed_on": obs_data.get('observed_on'),
        }

        # Import task via SDK
        project.import_tasks([{"data": task_data}])
        logger.info(f"Imported task {obs_id} to Project {PROJECT_ID}")
        return True

    except Exception as e:
        logger.error(f"Failed to sync task {obs_id}: {e}")
        return False


def wait_for_label_studio():
    """Waits for Label Studio to be ready with valid credentials."""
    logger.info(f"Waiting for Label Studio at {LS_URL}...")

    while True:
        success, message = check_label_studio_connection()

        if success:
            masked_key = f"{API_KEY[:4]}...{API_KEY[-4:]}" if len(API_KEY) > 8 else "***"
            logger.info(f"Label Studio connected! (API Key: {masked_key})")
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
