CREATE SCHEMA IF NOT EXISTS irion_validation;

CREATE TABLE IF NOT EXISTS irion_validation.runtime_marker (
    marker_name VARCHAR PRIMARY KEY,
    marker_value VARCHAR NOT NULL
);

DELETE FROM irion_validation.runtime_marker;
INSERT INTO irion_validation.runtime_marker VALUES
    ('initialization', 'ready'),
    ('configuration', 'irion-baseline');
