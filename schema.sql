-- Monarch Butterfly Observation Database Schema
-- This schema stores iNaturalist observation data and Label Studio annotations

-- Observations table: stores metadata from iNaturalist
CREATE TABLE IF NOT EXISTS observations (
    observation_id BIGINT PRIMARY KEY,
    inat_url TEXT NOT NULL,
    observed_on DATE,
    observer_login TEXT,
    observer_name TEXT,
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    location TEXT,
    image_url TEXT,
    image_local_path TEXT,
    quality_grade TEXT,
    num_identification_agreements INTEGER,
    num_identification_disagreements INTEGER,
    license TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(observation_id)
);

-- Labels table: stores annotations from Label Studio
CREATE TABLE IF NOT EXISTS labels (
    label_id SERIAL PRIMARY KEY,
    observation_id BIGINT NOT NULL,
    life_stage TEXT NOT NULL CHECK (life_stage IN ('Egg', 'Larva', 'Pupa', 'Adult', 'Unknown')),
    annotator TEXT,
    annotation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    label_studio_task_id INTEGER,
    label_studio_annotation_id INTEGER,
    FOREIGN KEY (observation_id) REFERENCES observations(observation_id) ON DELETE CASCADE
);

-- Index for faster lookups by observation_id in labels table
CREATE INDEX IF NOT EXISTS idx_labels_observation_id ON labels(observation_id);

-- Index for filtering by life stage
CREATE INDEX IF NOT EXISTS idx_labels_life_stage ON labels(life_stage);

-- View to join observations with their labels (for easy querying)
CREATE OR REPLACE VIEW observations_with_labels AS
SELECT
    o.observation_id,
    o.inat_url,
    o.observed_on,
    o.observer_login,
    o.observer_name,
    o.latitude,
    o.longitude,
    o.location,
    o.image_url,
    o.image_local_path,
    o.quality_grade,
    l.life_stage,
    l.annotator,
    l.annotation_date,
    l.label_studio_task_id
FROM observations o
LEFT JOIN labels l ON o.observation_id = l.observation_id;
