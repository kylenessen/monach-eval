# Monarch Phenology Evaluation Pipeline

A simplified tool to collect monarch butterfly observations from iNaturalist for phenology research.

## What This Does

1. Fetches random monarch butterfly observations from iNaturalist
2. Downloads the observation images to local storage
3. Stores observation metadata in a PostgreSQL database
4. Provides Label Studio for manual annotation
5. Stores annotations in the same database, linked to observations via image filenames

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

**Using Portainer Console (Recommended)**

1. Open your Portainer web interface
2. Navigate to **Containers**
3. Find and click on **monarch-ingestor** container
4. Click **Console** (or **Exec Console**)
5. Select `/bin/bash` as the shell
6. Click **Connect**
7. Run the fetch script:

```bash
# Fetch 20 observations
python scripts/fetch_observations.py -n 20

# Fetch 50 observations
python scripts/fetch_observations.py -n 50

# Fetch with custom max attempts (useful when many duplicates exist)
python scripts/fetch_observations.py -n 100 --max-attempts 500
```

**Alternative: Docker CLI**

```bash
# If you have CLI access to your server
docker exec -it monarch-ingestor python scripts/fetch_observations.py -n 20
```

### 3. Import Images into Label Studio

After fetching observations, manually import the images into Label Studio:

1. Log into Label Studio (https://monarch-eval.baywood-labs.com)
2. Open your project
3. Click **Import** button
4. Select **Upload Files**
5. Navigate to the local files directory: `/data/images/`
6. Select all new `.jpg` files
7. Click **Import**

Label Studio will create tasks for each image.

### 4. Query the Database

You can connect to the database to view observations and annotations.

**Using Portainer Console:**

1. Open Portainer
2. Navigate to the **label-studio-db** or **monarch-ingestor** container
3. Open the console with `/bin/sh` or `/bin/bash`
4. Run: `psql -U postgres -d postgres`

**Useful Queries:**

```sql
-- Count total observations
SELECT COUNT(*) FROM observations;

-- View observations
SELECT observation_id, observed_on, observer_login, location
FROM observations
LIMIT 10;

-- Count annotations
SELECT COUNT(*) FROM task_completion;

-- View all annotations with full metadata
SELECT
    t.id as task_id,
    tc.result::json->0->'value'->'choices'->>0 as life_stage,
    o.observation_id,
    o.observer_login,
    o.observed_on,
    o.location,
    o.inat_url,
    tc.created_at as annotated_at
FROM task_completion tc
JOIN task t ON tc.task_id = t.id
JOIN observations o ON o.observation_id =
    CAST(
        regexp_replace(t.data->>'$undefined$', '.*images/(\d+)\.jpg.*', '\1')
        AS BIGINT
    )
ORDER BY tc.created_at DESC;

-- Exit psql
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
Images stored in data/images/ (filenames = observation_id.jpg)
    ↓
Manual import into Label Studio
    ↓
Annotate in Label Studio UI
    ↓
PostgreSQL (task & task_completion tables)
    ↓
Query joins tasks → observations via filename
```

**Components:**
- **PostgreSQL** - Single database storing both observations AND Label Studio data
- **fetch_observations.py** - Python script to collect observations from iNaturalist
- **Label Studio** - Web UI for annotation (stores tasks in same PostgreSQL database)
- **Cloudflare Tunnel** - Remote access to Label Studio
- **monarch-ingestor** - Docker container with Python environment for running scripts

**Key Insight:** Label Studio and your observations share the same PostgreSQL database. The connection between them is the image filename: `{observation_id}.jpg`. You can query everything together using SQL.

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

### fetch_observations.py
**Purpose:** Fetch random monarch observations from iNaturalist and store in database

**Run via Portainer Console:**
1. Portainer → Containers → monarch-ingestor → Console
2. Select `/bin/bash` → Connect
3. Run:
```bash
python scripts/fetch_observations.py -n 50
```

**Options:**
- `-n, --num` - Number of observations to fetch (default: 10)
- `--max-attempts` - Maximum fetch attempts (default: 3x requested number)

**What it does:**
- Queries iNaturalist for research-grade monarchs without life stage data
- Downloads images to `data/images/{observation_id}.jpg`
- Stores metadata in PostgreSQL `observations` table
- Automatically skips duplicates based on `observation_id`

**Example:**
```bash
# Fetch 20 new observations
python scripts/fetch_observations.py -n 20

# Fetch 100 with more retry attempts
python scripts/fetch_observations.py -n 100 --max-attempts 500
```

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

## Using Label Studio for Annotation

Label Studio is running at `https://monarch-eval.baywood-labs.com` and shares the same PostgreSQL database as your observations.

### 1. Label Studio Configuration

Your Label Studio project should use the labeling config from `label_studio_config.xml`.

**To set up the configuration:**
1. Log into Label Studio
2. Go to your project → Settings → Labeling Interface
3. Copy the contents of `label_studio_config.xml` and paste it in
4. Click Save

**Features:**
- **Life Stage Selection:** Egg, Larva, Pupa, Adult, Unknown
- **Conditional Sub-options:**
  - **Adult:** Resting, Flying, Nectaring, Clustering, Mating, Ovipositing, Other (with text field)
  - **Larva:** Early instar, Late instar, Other (with text field)
  - **Unknown:** Text field required to explain
  - **Egg/Pupa:** No sub-options needed
- All sub-options are required and single-selection
- Instructions displayed at bottom of interface

### 2. Workflow

**Step 1: Fetch observations**
```bash
# In Portainer → monarch-ingestor container console
python scripts/fetch_observations.py -n 20
```

**Step 2: Import images into Label Studio**
1. Login to Label Studio
2. Open your project
3. Click **Import**
4. Select **Upload Files**
5. Choose files from `/data/images/` directory
6. Click **Import**

**Step 3: Annotate**
- Work through tasks in Label Studio UI
- Select life stage for each monarch observation
- Annotations automatically save to the database

**Step 4: Query your data**

Connect to the database via Portainer console (see "Query the Database" section above) and run:

```sql
-- View all annotations with metadata
SELECT
    t.id as task_id,
    tc.result::json->0->'value'->'choices'->>0 as life_stage,
    o.observation_id,
    o.observer_login,
    o.observed_on,
    o.location,
    o.inat_url
FROM task_completion tc
JOIN task t ON tc.task_id = t.id
JOIN observations o ON o.observation_id =
    CAST(
        regexp_replace(t.data->>'$undefined$', '.*images/(\d+)\.jpg.*', '\1')
        AS BIGINT
    )
ORDER BY tc.created_at DESC;
```

This query joins Label Studio's `task` and `task_completion` tables with your `observations` table using the observation_id extracted from the image filename.

## Project Philosophy

This project uses a **SIMPLE, MANUAL WORKFLOW** that avoids API complexity:

- **Database-first**: Everything in one PostgreSQL database (observations + Label Studio)
- **Manual import**: No API calls - just upload files through Label Studio UI
- **Filename-based linking**: Image filenames (`{observation_id}.jpg`) connect tasks to observations
- **Query-based analysis**: Use SQL to join all your data together
- **Portainer-managed**: Run scripts via Portainer console, no SSH needed
- **Minimal dependencies**: Only `requests`, `python-dotenv`, and `psycopg2`

**Why avoid the Label Studio API?** The authentication layer is complex and unreliable. The manual workflow is faster and more transparent.
