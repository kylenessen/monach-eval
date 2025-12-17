# Monarch Phenology Evaluation Pipeline

A simple, robust tool to download monarch butterfly observations from iNaturalist and sync them to Label Studio for annotation.

## What This Does

1. Fetches random monarch butterfly observations from iNaturalist
2. Downloads the observation images
3. Imports them as tasks into Label Studio for annotation
4. Tracks processed observations to avoid duplicates

## Quick Setup

### 1. Configure Environment Variables

Copy `config.env` and fill in your credentials:

```bash
cp config.env .env
```

Edit `.env` and set:

- `LABEL_STUDIO_API_TOKEN` - Your API token from Label Studio (see below)
- `TUNNEL_TOKEN` - Your Cloudflare tunnel token (optional)
- `SECRET_KEY` - Random string for Django sessions

### 2. Get Your Label Studio API Token

1. Start Label Studio: `docker-compose up -d label-studio`
2. Open http://localhost:8089
3. Login with your credentials
4. Click your user icon → Account & Settings
5. Select "Personal Access Token"
6. Copy the entire token (starts with "ey...")
7. Paste it into `.env` as `LABEL_STUDIO_API_TOKEN`

Note: The script automatically tries both "Token" and "Bearer" header formats, so it works with both PAT and legacy tokens.

### 3. Create a Project in Label Studio

1. In Label Studio, click "Create Project"
2. Name it (e.g., "Monarch Phenology")
3. Go to Settings > Labeling Interface
4. Add this configuration:

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
</View>
```

5. Note the Project ID (usually 1 for your first project)
6. Update `.env` with `LABEL_STUDIO_PROJECT_ID=1`

### 4. Start Everything

```bash
docker-compose up -d
```

Check logs:
```bash
docker logs -f monarch-ingestor
```

## Architecture

- **Label Studio** - Web UI for annotation (port 8089)
- **PostgreSQL** - Database backend
- **Ingestor** - Python script that downloads images and creates tasks
- **Cloudflare Tunnel** - Optional remote access

## Troubleshooting

### "Auth token invalid with both 'Token' and 'Bearer' formats"
- Get a fresh token from Label Studio's Account & Settings
- Make sure you copied the ENTIRE token (they're very long)
- Try regenerating the token if it's expired

### "Project not found"
- Check that `LABEL_STUDIO_PROJECT_ID` matches your actual project ID
- You can see the project ID in the URL when viewing a project

### Images not showing in Label Studio
- Make sure the project labeling config includes `<Image name="image" value="$image"/>`
- Check that Label Studio has permission to access `/label-studio/data/images`

## Data Storage

- `data/images/` - Downloaded monarch images
- `data/mydata/` - Label Studio data and exports
- `data/postgres-data/` - PostgreSQL database
- `data/processed_observations.txt` - Tracking file for processed observations

## How It Works

The ingestion script:
1. Uses your API token to authenticate with Label Studio (tries both header formats automatically)
2. Queries iNaturalist API for research-grade monarch observations without life stage data
3. Downloads observation images to `data/images/`
4. Creates tasks in Label Studio via REST API
5. Logs processed observation IDs to avoid duplicates
6. Runs continuously with 2-second delays between observations

## Simplifications Made

This project was rewritten to be **SIMPLE and ROBUST**:

- Removed Label Studio SDK dependency (was causing auth issues)
- Uses direct REST API calls instead
- Auto-detects correct token format ("Token" vs "Bearer")
- Only requires `requests` and `python-dotenv`
- Clear error messages with specific troubleshooting hints
