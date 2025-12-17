# Monarch Phenology Evaluation Pipeline

A simplified tool to collect monarch butterfly observations from iNaturalist for phenology research.

## What This Does

1. Fetches random monarch butterfly observations from iNaturalist
2. Downloads the observation images to local storage
3. Stores observation metadata in a PostgreSQL database
4. Tracks processed observations to avoid duplicates
5. Prepares data for later annotation (e.g., with Label Studio)

## Why This Approach?

This simplified workflow decouples data collection from annotation:

- **Data Collection**: Run the fetch script to gather observations and images
- **Storage**: All metadata stored in PostgreSQL, joined by observation_id
- **Annotation**: Label Studio (or other tools) can be used separately
- **Integration**: Labels can be imported back into the database later

## Quick Setup

### Deployment Options

**Option A: Portainer (Recommended for Home Lab)**

If you're managing this stack with Portainer:

1. Add this repository as a Git-based stack in Portainer
2. Set the repository URL to your fork/clone
3. Configure environment variables in Portainer's stack settings
4. Deploy the stack - database and Label Studio will start automatically
5. The `ingestor` service won't start automatically (it uses the `tools` profile for on-demand use)

**Option B: Docker Compose CLI**

```bash
# Start core services (database, Label Studio, tunnel)
docker-compose up -d

# The database schema will be automatically initialized on first run
```

### 1. Configure Environment Variables

Copy the template and configure your settings:

```bash
cp config.env .env
```

Edit `.env` with your settings. At minimum, configure:
- Database credentials (defaults are fine for local development)
- `SECRET_KEY` for Django (generate a random string)
- `TUNNEL_TOKEN` if using Cloudflare Tunnel for remote access

### 2. Fetch Observations

Run the fetch script to download observations and store them in the database.

**Option A: Run on host machine (requires Python 3.10+)**

```bash
pip install -r requirements.txt
python scripts/fetch_observations.py -n 20
```

**Option B: Run in Docker (Recommended with Portainer)**

```bash
# Using docker-compose
docker-compose run --rm ingestor python scripts/fetch_observations.py -n 20

# Or exec into the container if using Portainer
docker exec -it monarch-ingestor python scripts/fetch_observations.py -n 20
```

**Usage Options:**
```bash
# Fetch 10 observations (default)
python scripts/fetch_observations.py

# Fetch 50 observations
python scripts/fetch_observations.py -n 50

# Fetch with custom max attempts (useful when many duplicates exist)
python scripts/fetch_observations.py -n 100 --max-attempts 500
```

### 3. Query the Database

You can connect to the database to view collected observations:

```bash
# Connect to PostgreSQL
docker exec -it label-studio-db psql -U postgres -d postgres

# View all observations
SELECT observation_id, observed_on, observer_login, location FROM observations LIMIT 10;

# Count total observations
SELECT COUNT(*) FROM observations;

# Exit psql
\q
```

## Architecture

```
iNaturalist API
    ↓
fetch_observations.py (batch fetching)
    ↓
PostgreSQL Database (observations table)
    ↓
Images stored in data/images/
    ↓
[Future: Label Studio or other annotation tools]
    ↓
[Future: Labels imported to labels table]
```

**Components:**
- **PostgreSQL** - Central database for all observation metadata and labels
- **fetch_observations.py** - Python script to collect observations
- **Label Studio** (optional) - Can be used for annotation
- **Cloudflare Tunnel** (optional) - Remote access to Label Studio

## Database Schema

The database has two main tables:

**observations** - Stores iNaturalist observation metadata
- `observation_id` (PRIMARY KEY) - Unique iNaturalist observation ID
- `inat_url` - Link to observation on iNaturalist
- `observed_on` - Date of observation
- `observer_login`, `observer_name` - Who made the observation
- `latitude`, `longitude`, `location` - Where it was observed
- `image_url` - Original image URL from iNaturalist
- `image_local_path` - Path to downloaded image
- `quality_grade`, licenses, agreements, etc.

**labels** - Stores phenology annotations (populated later)
- `label_id` (PRIMARY KEY)
- `observation_id` (FOREIGN KEY) - Links to observations table
- `life_stage` - One of: Egg, Larva, Pupa, Adult, Unknown
- `annotator` - Who made the annotation
- `annotation_date` - When it was annotated
- `label_studio_task_id`, `label_studio_annotation_id` - Integration fields

## Available Scripts

### 1. fetch_observations.py
**Purpose:** Fetch random monarch observations from iNaturalist and store in database

```bash
python scripts/fetch_observations.py -n 50
```

**Options:**
- `-n, --num` - Number of observations to fetch (default: 10)
- `--max-attempts` - Maximum fetch attempts (default: 3x requested number)

**What it does:**
- Queries iNaturalist for research-grade monarchs without life stage data
- Downloads images to `data/images/`
- Stores metadata in PostgreSQL `observations` table
- Automatically skips duplicates based on `observation_id`

### 2. sync_to_labelstudio.py
**Purpose:** Push observations from database to Label Studio for annotation

```bash
python scripts/sync_to_labelstudio.py -n 50 --skip-duplicates
```

**Options:**
- `-n, --num` - Number of observations to sync (default: all)
- `--skip-duplicates` - Check Label Studio for existing tasks before syncing

**What it does:**
- Reads observations from PostgreSQL
- Creates corresponding tasks in Label Studio
- Uses local file paths (Label Studio serves them via mounted volume)
- Includes metadata like observation_id, iNaturalist URL, date, location

**Prerequisites:**
- Label Studio must be running
- `LABEL_STUDIO_API_TOKEN` and `LABEL_STUDIO_PROJECT_ID` must be configured
- Project must have appropriate labeling configuration

## Troubleshooting

### Database connection failed
- Make sure PostgreSQL is running: `docker ps | grep label-studio-db`
- Check that port 5432 is not already in use
- Verify credentials in docker-compose.yml match your `.env` file

### No observations found
- Check your internet connection
- Verify iNaturalist API is accessible: `curl https://api.inaturalist.org/v1/observations`
- The script filters for research-grade monarchs without life stage data

### Images not downloading
- Check that `data/images/` directory exists and is writable
- Verify you have disk space available
- Image URLs from iNaturalist may occasionally be unavailable

## Data Storage

- `data/images/` - Downloaded monarch images (named by observation_id)
- `data/postgres-data/` - PostgreSQL database files
- `data/mydata/` - Label Studio data (if using Label Studio)
- `schema.sql` - Database schema definition

## How It Works

The fetch script:
1. Connects to PostgreSQL database
2. Queries iNaturalist API for research-grade monarch observations without life stage data
3. Randomly selects observations to avoid bias
4. Downloads observation images to `data/images/`
5. Stores metadata in the `observations` table
6. Checks for duplicates using `observation_id` as unique key
7. Continues until the requested batch size is reached

## Using Label Studio for Annotation (Optional)

Label Studio is already configured and running at `https://monarch-eval.baywood-labs.com`.

### 1. Verify Label Studio Configuration

Your Label Studio instance should have a project with this labeling config:

```xml
<View>
  <Image name="image" value="$image"/>
  <Choices name="life_stage" toName="image" required="true">
    <Choice value="Egg"/>
    <Choice value="Larva"/>
    <Choice value="Pupa"/>
    <Choice value="Adult"/>
    <Choice value="Unknown"/>
  </Choices>
  <Header value="Observation Details:"/>
  <Text name="obs_id" value="$observation_id"/>
  <HyperText name="url" value="$inat_url"/>
  <Text name="date" value="$observed_on"/>
  <Text name="observer" value="$observer"/>
  <Text name="location" value="$location"/>
</View>
```

### 2. Get Your API Token

1. Login to Label Studio at https://monarch-eval.baywood-labs.com
2. Go to Account & Settings → Personal Access Token
3. Copy the token and add it to your `.env` file as `LABEL_STUDIO_API_TOKEN`
4. Note your Project ID (visible in the project URL)

### 3. Sync Observations to Label Studio

Use the sync script to push observations from the database to Label Studio:

```bash
# Sync all observations
python scripts/sync_to_labelstudio.py

# Sync only the latest 50 observations
python scripts/sync_to_labelstudio.py -n 50

# Check for duplicates before syncing (slower but safer)
python scripts/sync_to_labelstudio.py --skip-duplicates

# Or run in Docker
docker-compose run --rm ingestor python scripts/sync_to_labelstudio.py -n 50
```

### 4. Annotate in Label Studio

1. Open https://monarch-eval.baywood-labs.com
2. Navigate to your project
3. Start annotating observations with their life stages
4. Label Studio automatically saves your annotations to its database

### 5. Import Labels Back to Database (Future)

After annotation, you can export labels from Label Studio and import them into the `labels` table. A helper script for this will be created when needed.

## Project Philosophy

This project was redesigned to be **SIMPLE and DECOUPLED**:

- **Database-first**: All data stored in PostgreSQL, not text files
- **Batch processing**: Run the script when you need data, not continuously
- **Separation of concerns**: Data collection separate from annotation
- **Flexible integration**: Can use any annotation tool, not locked to Label Studio
- **Minimal dependencies**: Only `requests`, `python-dotenv`, and `psycopg2`
- **Clear schema**: Easy to query and analyze data with SQL
