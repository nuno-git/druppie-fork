-- Current schema snapshot for v1 (fresh install)
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    board TEXT NOT NULL,
    current_player TEXT NOT NULL,
    game_active BOOLEAN NOT NULL,
    result TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
