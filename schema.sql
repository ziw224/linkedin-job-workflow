-- Job Workflow OSS — MySQL Schema
-- Run: mysql -u root -p job_workflow < schema.sql

CREATE DATABASE IF NOT EXISTS job_workflow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE job_workflow;

-- ── Users ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    discord_id      VARCHAR(20)  PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255),
    linkedin        VARCHAR(255),
    portfolio       VARCHAR(255),
    bio             TEXT,
    resume_pdf_prefix VARCHAR(255) DEFAULT 'Resume',
    notify_channel_id VARCHAR(20),          -- Discord channel to send reports to
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ── Per-user search preferences ────────────────────────────────────────────────
-- Each user can override global search_config.json.
-- NULL fields fall back to global defaults.
CREATE TABLE IF NOT EXISTS user_search_configs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    discord_id      VARCHAR(20)  NOT NULL,
    category        ENUM('sde', 'ai') NOT NULL,
    keywords        JSON         NOT NULL,      -- ["Software Engineer", ...]
    experience_levels JSON       NOT NULL,      -- [2, 3] (LinkedIn codes)
    target_count    INT          DEFAULT 5,
    locations       JSON         DEFAULT NULL,  -- NULL = use global locations
    FOREIGN KEY (discord_id) REFERENCES users(discord_id) ON DELETE CASCADE,
    UNIQUE KEY uq_user_category (discord_id, category)
);

-- ── Seen jobs (per-user deduplication) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS seen_jobs (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    discord_id      VARCHAR(20)  NOT NULL,
    job_id          VARCHAR(255) NOT NULL,
    seen_at         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (discord_id) REFERENCES users(discord_id) ON DELETE CASCADE,
    UNIQUE KEY uq_user_job (discord_id, job_id),
    INDEX idx_discord_id (discord_id)
);

-- ── Job runs ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS job_runs (
    run_id          VARCHAR(36)  PRIMARY KEY,   -- UUID from main.py
    discord_id      VARCHAR(20)  NOT NULL,
    started_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP    NULL,
    duration_ms     INT          NULL,
    status          ENUM('running', 'done', 'aborted', 'error') DEFAULT 'running',
    jobs_total      INT          DEFAULT 0,
    jobs_ok         INT          DEFAULT 0,
    FOREIGN KEY (discord_id) REFERENCES users(discord_id) ON DELETE CASCADE,
    INDEX idx_discord_started (discord_id, started_at)
);

-- ── Job results ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS job_results (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    run_id          VARCHAR(36)  NOT NULL,
    discord_id      VARCHAR(20)  NOT NULL,
    job_id          VARCHAR(255) NOT NULL,
    title           VARCHAR(500),
    company         VARCHAR(255),
    location        VARCHAR(255),
    url             TEXT,
    success         BOOLEAN      DEFAULT FALSE,
    html_path       TEXT,
    pdf_path        TEXT,
    cover_letter_path TEXT,
    why_company_path  TEXT,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES job_runs(run_id) ON DELETE CASCADE,
    INDEX idx_run_id (run_id),
    INDEX idx_discord_date (discord_id, created_at)
);
