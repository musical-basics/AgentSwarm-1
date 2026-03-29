import os
import json
import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv

load_dotenv(".env.local")

DATABASE_URL = os.getenv("DATABASE_URL")
STATE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".ide_state.json"))

def get_db_connection():
    if not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"Warning: Failed to connect to Neon DB: {e}")
        return None

def get_global_settings() -> dict:
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                # Ensure the table exists by requiring user to run the schema manually. We'll just try to select.
                cur.execute("SELECT last_workspace, layout, chat_agent_company, chat_agent_model FROM global_settings WHERE id = 1;")
                row = cur.fetchone()
                if row:
                    return {
                        "last_workspace": row[0] or "",
                        "layout": row[1] or {},
                        "chatAgentCompany": row[2] or "google",
                        "chatAgentModel": row[3] or "google/gemini-2.5-flash",
                    }
        except Exception as e:
            print(f"Warning: DB read error (did you run the schema?): {e}")
        finally:
            conn.close()

    # Fallback to local json
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_global_settings(settings: dict):
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                # Upsert into global_settings
                cur.execute("""
                    INSERT INTO global_settings (id, last_workspace, layout, chat_agent_company, chat_agent_model) 
                    VALUES (1, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET 
                        last_workspace = EXCLUDED.last_workspace,
                        layout = EXCLUDED.layout,
                        chat_agent_company = EXCLUDED.chat_agent_company,
                        chat_agent_model = EXCLUDED.chat_agent_model;
                """, (
                    settings.get("last_workspace", ""),
                    Json(settings.get("layout", {})),
                    settings.get("chatAgentCompany", "google"),
                    settings.get("chatAgentModel", "google/gemini-2.5-flash")
                ))
            conn.commit()
            print(f"[DB] Successfully saved global_settings to NeonDB (Company: {settings.get('chatAgentCompany')}, Model: {settings.get('chatAgentModel')})")
            return
        except Exception as e:
            print(f"Warning: DB write error: {e}")
            conn.rollback()
        finally:
            conn.close()

    # Fallback to local json
    print("[DB] No connection string found, falling back to local .ide_state.json for global settings")
    with open(STATE_FILE, "w") as f:
        json.dump(settings, f)

def get_workspace_config(path: str) -> dict:
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT config FROM workspaces WHERE path = %s;", (path,))
                row = cur.fetchone()
                if row:
                    return row[0] or {}
        except Exception as e:
            print(f"Warning: DB read workspace error: {e}")
        finally:
            conn.close()
    
    # Fallback to local file in workspace
    config_file = os.path.join(path, "swarm_config.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_workspace_config(path: str, config: dict):
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO workspaces (path, config) 
                    VALUES (%s, %s)
                    ON CONFLICT (path) DO UPDATE SET config = EXCLUDED.config;
                """, (path, Json(config)))
            conn.commit()
            print(f"[DB] Successfully saved workspace config to NeonDB for path: {path}")
            return
        except Exception as e:
            print(f"Warning: DB write workspace error: {e}")
            conn.rollback()
        finally:
            conn.close()

    # Fallback to local file
    print(f"[DB] No connection string found, falling back to local swarm_config.json for workspace: {path}")
    config_file = os.path.join(path, "swarm_config.json")
    try:
        with open(config_file, "w") as f:
            json.dump(config, f)
    except:
        pass
