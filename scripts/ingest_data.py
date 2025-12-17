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

def sync_to_label_studio(filename, obs_id, obs_data):
    """Creates a task in Label Studio."""
    if not API_KEY or not PROJECT_ID:
        logger.warning("Label Studio credentials not set. Skipping LS sync.")
        return

    ls = Client(url=LS_URL, api_key=API_KEY)
    project = ls.get_project(PROJECT_ID)
    
    # Construct the local URL that Label Studio container can see
    # e.g., /data/images/12345.jpg matches LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT
    image_path = f"/data/images/{filename}" 
    
    task_data = {
        "image": image_path,
        "observation_id": obs_id,
        "inat_url": obs_data.get('uri'),
        "observed_on": obs_data.get('observed_on'),
    }
    
    project.import_tasks([{"data": task_data}])
    logger.info(f"Imported task {obs_id} to Project {PROJECT_ID}")

def main():
    logger.info("Starting Ingestion Pipeline...")
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
