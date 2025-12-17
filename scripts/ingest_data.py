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
    """
    Fetches a random research-grade Monarch observation without Life Stage annotation.
    Strategy: Get total count, then pick a random offset.
    """
    params = {
        "taxon_id": MONARCH_TAXON_ID,
        "quality_grade": "research",
        "without_term_id": 1, # Filter out observations with Life Stage annotation
        "photos": "true",
        "per_page": 1,
    }
    
    # First request to get total results
    try:
        response = requests.get(INAT_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        total_results = data['total_results']
        
        # Limit offset to 10000 (iNat API limitation)
        # If total > 10000, we can't random access beyond 10k via offset easily.
        # Fallback: Randomize parameters or accept only recent 10k?
        # Better Strategy: Randomly sort by 'id'? No, 'random' not supported.
        # Randomly pick a year?
        # For now, let's just pick a random offset within the first 200 pages (limit of shallow random).
        # To get truly deep random, we might need to randomize date ranges.
        
        max_offset = min(total_results, 9000) # Keep safe below 10k
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

def get_ls_client():
    """
    Creates and authenticates a Label Studio Client with the correct header fix.
    """
    if not API_KEY or API_KEY == "placeholder":
        return None

    # Determine header prefix based on token format
    auth_header_name = "Authorization"
    if API_KEY.startswith("ey"):
        auth_header_value = f"Bearer {API_KEY}"
        token_type = "JWT"
    else:
        auth_header_value = f"Token {API_KEY}"
        token_type = "Token"

    ls = Client(url=LS_URL, api_key=API_KEY)
    
    # CRITICAL FIX: The SDK resets headers on every request or doesn't use the client's headers safely.
    # We must monkey-patch the `make_request` method to ensure our header wins.
    original_make_request = ls.make_request

    def patched_make_request(method, url, *args, **kwargs):
        # Update the client's headers to ensure our token is used
        ls.headers.update({auth_header_name: auth_header_value})
        
        # Also update the session headers if available, as this is often where requests looks
        if hasattr(ls, 'session'):
            ls.session.headers.update({auth_header_name: auth_header_value})

        # Remove 'headers' from kwargs if present to prevent "multiple values for keyword argument 'headers'"
        if 'headers' in kwargs:
            _ = kwargs.pop('headers')
        
        return original_make_request(method, url, *args, **kwargs)

    # Apply the patch
    ls.make_request = patched_make_request
    
    # Store token type for logging if needed (optional)
    ls._token_type = token_type
    return ls

def sync_to_label_studio(filename, obs_id, obs_data):
    """Creates a task in Label Studio."""
    ls = get_ls_client()
    if not ls:
        logger.warning("Label Studio credentials not set. Skipping LS sync.")
        return

    try:
        project = ls.get_project(PROJECT_ID)
        
        # Construct the local URL that Label Studio container can see
        image_path = f"/data/images/{filename}" 
        
        task_data = {
            "image": image_path,
            "observation_id": obs_id,
            "inat_url": obs_data.get('uri'),
            "observed_on": obs_data.get('observed_on'),
        }
        
        project.import_tasks([{"data": task_data}])
        logger.info(f"Imported task {obs_id} to Project {PROJECT_ID}")
    except Exception as e:
        logger.error(f"Failed to sync task {obs_id}: {e}")

def wait_for_label_studio():
    """Waits for Label Studio to be ready before starting."""
    logger.info(f"Waiting for Label Studio at {LS_URL}...")
    
    while True:
        try:
            ls = get_ls_client()
            if not ls:
                logger.warning("LABEL_STUDIO_API_KEY is not set or is 'placeholder'. Waiting for user to configure it...")
                time.sleep(10)
                continue

            ls.check_connection()
            masked_key = f"{API_KEY[:4]}...{API_KEY[-4:]}" if len(API_KEY) > 8 else "***"
            logger.info(f"Label Studio is up and running with valid API Key! (Key: {masked_key}, Type: {ls._token_type})")
            return
            
        except Exception as e:
            logger.warning(f"Connection check failed: {e}. Retrying in 5s...")
            
        time.sleep(5)

def main():
    logger.info("Starting Ingestion Pipeline...")
    wait_for_label_studio()
    processed = load_processed_ids()
    
    # Run loop
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
            
        # Get Primary Photo URL (Medium size)
        photos = obs.get('photos', [])
        if not photos:
            continue
            
        photo_url = photos[0]['url'].replace('square', 'medium')
        
        logger.info(f"Processing Observation {obs_id}...")
        
        # Download
        filename = download_image(photo_url, obs_id)
        if filename:
            # Sync
            sync_to_label_studio(filename, obs_id, obs)
            # Mark processed
            save_processed_id(obs_id)
            
        # Rate limit politeness
        time.sleep(2)

if __name__ == "__main__":
    main()
