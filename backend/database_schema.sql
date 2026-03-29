CREATE TABLE IF NOT EXISTS global_settings (
    id SERIAL PRIMARY KEY,
    last_workspace TEXT,
    layout JSONB,
    chat_agent_company TEXT,
    chat_agent_model TEXT
);

CREATE TABLE IF NOT EXISTS workspaces (
    path TEXT PRIMARY KEY,
    config JSONB
);

-- Insert a default row for settings (if empty)
INSERT INTO global_settings (id, last_workspace, layout, chat_agent_company, chat_agent_model) 
VALUES (1, '', '{}', 'google', 'google/gemini-2.5-flash')
ON CONFLICT (id) DO NOTHING;
