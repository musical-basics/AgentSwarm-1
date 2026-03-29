import asyncio
import os
import uvicorn
import logging
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from openai import AsyncOpenAI
import httpx

DOTENV_PATH = os.path.join(os.path.dirname(__file__), ".env.local")
load_dotenv(DOTENV_PATH)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("swarm.log"),
        logging.StreamHandler()
    ]
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LLMEngine:
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Fallback to a dummy key if not set, or it will throw
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key or "DUMMY_KEY",
        )

    async def generate(self, system_prompt: str, user_prompt: str, model_name: str = "google/gemini-2.5-flash", is_json: bool = False, max_tokens: int = 8192) -> tuple[str, any]:
        kwargs = {
            "extra_headers": {
                "HTTP-Referer": "http://localhost:3008",
                "X-Title": "Flowmind IDE",
            },
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_tokens,
        }
        if is_json:
            kwargs["response_format"] = {"type": "json_object"}
            
        logging.info(f"[LLM Generate] Starting request to model: {model_name}, is_json: {is_json}")
        try:
            response = await self.client.chat.completions.create(**kwargs)
            logging.info(f"[LLM Generate] Success for model: {model_name}")
            return response.choices[0].message.content, response.usage
        except Exception as e:
            logging.error(f"[LLM Generate] Failed for model {model_name}: {e}")
            raise

    async def generate_stream(self, system_prompt: str, user_prompt: str, model_name: str = "google/gemini-2.5-flash", is_json: bool = False):
        kwargs = {
            "extra_headers": {
                "HTTP-Referer": "http://localhost:6500",
                "X-Title": "Flowmind IDE",
            },
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 8192,
            "stream": True,
        }
        if is_json:
            kwargs["response_format"] = {"type": "json_object"}
            
        stream = await self.client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

from db import get_global_settings, save_global_settings, get_workspace_config, save_workspace_config

def load_ide_state() -> dict:
    return get_global_settings()

def save_ide_state(state: dict):
    save_global_settings(state)

active_ws_connections = set()
active_pty_fds = set()
ws_locks = {}
cached_models = []
active_swarm_tasks = {}

async def fetch_openrouter_models():
    global cached_models
    if cached_models:
        return cached_models
    try:
        api_key = os.getenv('OPENROUTER_API_KEY')
        if not api_key:
            print("WARNING: OPENROUTER_API_KEY is not set!")
            
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            if resp.status_code == 200:
                data = resp.json()
                if "data" in data:
                    sorted_data = sorted(data["data"], key=lambda x: x.get("name", "").lower())
                    cached_models = sorted_data
                    return cached_models
            else:
                print(f"OpenRouter API returned non-200 status: {resp.status_code} - {resp.text}")
    except Exception as e:
        import traceback
        print(f"Failed to fetch models via backend proxy: {e}")
        traceback.print_exc()
    return []

def calculate_cost_payload(model_id: str, usage) -> dict:
    if not usage: return {}
    
    prompt_tokens = getattr(usage, "prompt_tokens", 0)
    completion_tokens = getattr(usage, "completion_tokens", 0)
    
    cost_data = {
        "model": model_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_cost_usd": 0.0
    }
    
    for m in cached_models:
        if m.get("id") == model_id:
            pricing = m.get("pricing", {})
            p_cost = float(pricing.get("prompt", 0)) * prompt_tokens
            c_cost = float(pricing.get("completion", 0)) * completion_tokens
            cost_data["total_cost_usd"] = round(p_cost + c_cost, 6)
            break
            
    return cost_data

async def safe_send(ws: WebSocket, data: dict):
    if ws not in ws_locks:
        ws_locks[ws] = asyncio.Lock()
    async with ws_locks[ws]:
        try:
            await ws.send_json(data)
        except Exception:
            pass

import time
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

class WorkspaceWatcher(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self._timer = None

    def on_any_event(self, event):
        if event.is_directory or "___" in event.src_path or ".DS_Store" in event.src_path:
            return
        
        # Debounce broadcast
        if self._timer:
            self._timer.cancel()
        
        # Get active running loop safely
        try:
            loop = asyncio.get_running_loop()
            self._timer = loop.call_later(0.3, lambda: asyncio.create_task(self.broadcast()))
        except RuntimeError:
            pass
            
    async def broadcast(self):
        try:
            files = fs_manager.list_files()
            workspace_name = os.path.basename(fs_manager.workspace_path) or "Workspace"
            dead_ws = set()
            for ws in active_ws_connections:
                try:
                    await safe_send(ws, {"event": "file_list", "files": files, "workspace_name": workspace_name})
                except Exception:
                    dead_ws.add(ws)
            for ws in dead_ws:
                active_ws_connections.remove(ws)
        except Exception as e:
            print(f"Watchdog broadcast error: {e}")

global_observer = Observer()
global_watcher = WorkspaceWatcher()

class FileSystemManager:
    def __init__(self, workspace_path: str):
        self.workspace_path = os.path.abspath(workspace_path)
        os.makedirs(self.workspace_path, exist_ok=True)

    def _get_safe_path(self, relative_path: str) -> str:
        # Prevent absolute paths or trailing path traversal
        if os.path.isabs(relative_path):
            relative_path = relative_path.lstrip("/")
        normalized = os.path.normpath(relative_path)
        safe_path = os.path.abspath(os.path.join(self.workspace_path, normalized))
        
        # Security hard-stop: Block any path parsing that escapes the workspace boundary
        if not safe_path.startswith(self.workspace_path):
            raise ValueError(f"SECURITY ALERT: Access denied. Agent attempted to write to: {safe_path}. Operations are strictly sandboxed.")
        return safe_path

    def list_files(self, relative_path: str = ""):
        safe_path = self._get_safe_path(relative_path)
        if not os.path.exists(safe_path) or not os.path.isdir(safe_path):
            return []
            
        def build_tree(current_dir):
            tree = []
            for item in os.listdir(current_dir):
                if item.startswith('.'):
                    continue
                item_path = os.path.join(current_dir, item)
                is_dir = os.path.isdir(item_path)
                
                node = {
                    "name": item,
                    "path": os.path.relpath(item_path, self.workspace_path),
                    "is_dir": is_dir
                }
                
                if is_dir:
                    node["children"] = build_tree(item_path)
                    
                tree.append(node)
                
            # Sort folders first, then files
            tree.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
            return tree
            
        return build_tree(safe_path)

    def read_file(self, relative_path: str) -> str:
        safe_path = self._get_safe_path(relative_path)
        with open(safe_path, "r", encoding="utf-8") as f:
            return f.read()

    def write_file(self, relative_path: str, content: str):
        safe_path = self._get_safe_path(relative_path)
        # Securely build directories inside boundaries
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)

    def format_all_files(self) -> str:
        """Returns a single string containing the paths and contents of all files in the workspace.
        This is used to inject existing context into LLM prompts without needing complex tool usage.
        Avoids reading large binaries or non-text files."""
        out = []
        for root, dirs, files in os.walk(self.workspace_path):
            # Exclude hidden directories like .git
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            if '_swarm_artifacts' in dirs:
                dirs.remove('_swarm_artifacts') # dont feed artifacts back in if not needed
                
            for file in files:
                if file.startswith('.') or file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.zip', '.tar', '.gz')):
                    continue
                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, self.workspace_path)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    out.append(f"--- FILE: {rel_path} ---\n{content}\n")
                except UnicodeDecodeError:
                    pass # ignore binary files
        if not out:
            return "No files in the workspace yet."
        return "\n".join(out)

WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../workspace_sandbox"))
_initial_state = load_ide_state()
_saved_workspace = _initial_state.get("last_workspace")
if _saved_workspace and os.path.isdir(_saved_workspace):
    WORKSPACE_DIR = _saved_workspace

fs_manager = FileSystemManager(WORKSPACE_DIR)

try:
    global_observer.schedule(global_watcher, fs_manager.workspace_path, recursive=True)
except RuntimeError as e:
    if "already scheduled" not in str(e):
        raise e
global_observer.start()

llm = LLMEngine(os.getenv("OPENROUTER_API_KEY", ""))

import re
import subprocess

async def execute_agent_chat(websocket: WebSocket, message: str, model: str, history: list, fs_mgr: FileSystemManager, models_dict: dict = None):
    if models_dict is None:
        models_dict = {}
    """Direct AI chat agent with sandboxed terminal command execution."""
    workspace = fs_mgr.workspace_path

    system_prompt = f"""You are a helpful AI coding assistant embedded in the Flowmind IDE.
The user's current workspace is at: {workspace}
You can run shell commands inside the workspace sandbox by embedding them like this: <cmd>your shell command</cmd>
Rules:
- Commands are executed with cwd set to the workspace directory.
- Never access paths outside the workspace limit.
- Only run commands that are safe and relevant to the user's request.
- After running a command, interpret the output naturally and explain what happened.
- You can run multiple commands in one response if needed.
- If the user asks you to create, edit, or run files, do it via commands.
- If the user asks you to build an app, website, or 'run this through the swarm', DO NOT write the code yourself. Instead, you MUST FIRST ask 2-3 clarifying questions to gather exact requirements (e.g. tech stack, color palette, feature specifics, target audience). DO NOT use the <swarm> tag on the first prompt. Wait until the user has answered your questions and provided enough detail. Once you have a sufficient PRD context from the conversation, ONLY THEN delegate the build to the Swarm Engine by outputting exactly: <swarm>The comprehensive request details here...</swarm>
- ERROR HANDLING: If a command fails (e.g., "command not found: python"), analyze the error and TRY A FIX yourself in your next response! For example, on macOS, use `python3` instead of `python`. If a module is missing, run `<cmd>pip3 install module_name</cmd>` and then retry.
"""

    messages = [{"role": "system", "content": system_prompt}]
    # Include last 10 turns of history for context
    for h in history[-10:]:
        role = h.get("role", "user")
        if role == "agent":
            role = "assistant"
        messages.append({"role": role, "content": h.get("content", "")})
    messages.append({"role": "user", "content": message})

    # Stream typing indicator
    await safe_send(websocket,{"event": "agent_chat_typing", "model": model})

    try:
        response = await llm.client.chat.completions.create(
            extra_headers={"HTTP-Referer": "http://localhost:6500", "X-Title": "Flowmind IDE"},
            model=model,
            messages=messages,
            max_tokens=4000,
        )
        text = response.choices[0].message.content or ""
        usage = response.usage
    except Exception as e:
        await safe_send(websocket,{
            "event": "agent_chat_response",
            "text": f"⚠️ API Error: {str(e)}",
            "commands": [],
            "model": model,
        })
        return

    # Parse <swarm>...</swarm> blocks and trigger them
    swarm_pattern = re.compile(r'<swarm>(.*?)</swarm>', re.DOTALL)
    swarm_found = swarm_pattern.findall(text)
    
    # Parse <cmd>...</cmd> blocks and execute them
    cmd_pattern = re.compile(r'<cmd>(.*?)</cmd>', re.DOTALL)
    commands_found = cmd_pattern.findall(text)
    command_results = []

    for swarm_prompt in swarm_found:
        asyncio.create_task(execute_live_swarm(websocket, swarm_prompt.strip(), models_dict))
        command_results.append({"cmd": f"<swarm>{swarm_prompt.strip()[:50]}...</swarm>", "output": "🚀 Swarm Engine Triggered. Watch the simulator panel!"})

    for cmd_str in commands_found:
        cmd_str = cmd_str.strip()
        # Security: reject any cd or path traversal attempts outside workspace
        if ".." in cmd_str or cmd_str.startswith("/"):
            command_results.append({"cmd": cmd_str, "output": "⛔ Blocked: command attempts to access outside workspace."})
            continue
        try:
            process = await asyncio.create_subprocess_shell(
                cmd_str,
                cwd=workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "HOME": workspace}
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
                output = (stdout.decode() + stderr.decode()).strip() or "(no output)"
                command_results.append({"cmd": cmd_str, "output": output})
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except Exception:
                    pass
                command_results.append({"cmd": cmd_str, "output": "⚠️ Command timed out after 30s. Note: Interactive commands that prompt for user input are not supported here."})
        except Exception as e:
            command_results.append({"cmd": cmd_str, "output": f"⚠️ Error: {str(e)}"})

    # Refresh file tree if any commands ran (they might have created files)
    if command_results:
        files = fs_mgr.list_files()
        await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(workspace)})

    await safe_send(websocket,{
        "event": "agent_chat_response",
        "text": text,
        "commands": command_results,
        "model": model,
        "usage": {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens} if usage else {},
    })

# Token budget tiers: {complexity: max_tokens}
COMPLEXITY_BUDGETS = {
    1: 1024,   # Simple: a function, a regex, a short note
    2: 3072,   # Medium: a small script, a short blog post  
    3: 8192,   # Complex: full app, multi-file architecture
}



def normalize_models_dict(models_dict, complexity):
    if not models_dict: return {}
    res = {}
    for k, v in models_dict.items():
        if isinstance(v, dict):
            if complexity == 1:
                res[k] = v.get("easy", v.get("hard", "google/gemini-2.5-flash"))
            elif complexity == 2:
                res[k] = v.get("medium", v.get("hard", "google/gemini-2.5-flash"))
            else:
                res[k] = v.get("hard", "google/gemini-2.5-flash")
        else:
            res[k] = v
    return res

async def classify_intent(prompt: str, model_id: str) -> tuple[str, int]:
    """Returns (profile, complexity) where complexity is 1/2/3."""
    system_prompt = """
    Analyze the user prompt and categorize it into EXACTLY one of three profiles AND a complexity score.
    
    Profiles:
    - "enterprise": Complex software, multiple files, full apps, architecture planning.
    - "sniper": Single-file scripts, quick code fixes, simple regex, or single functions.
    - "newsroom": Creative writing, essays, blog posts, or non-code text generation.
    
    Complexity (how much output is expected):
    - 1 (simple): A one-liner, a short snippet, a quick fix, under 50 words.
    - 2 (medium): A single file, a short essay, a script under 200 lines.
    - 3 (complex): Multi-file apps, long-form writing, full architecture.
    
    Respond ONLY with a JSON object: {"profile": "enterprise" | "sniper" | "newsroom", "complexity": 1 | 2 | 3}
    """
    try:
        res, _ = await llm.generate(system_prompt, prompt, model_name=model_id, is_json=True)
        # Clean JSON
        clean_res = res.strip()
        if clean_res.startswith("```json"): clean_res = clean_res[7:]
        elif clean_res.startswith("```"): clean_res = clean_res[3:]
        if clean_res.endswith("```"): clean_res = clean_res[:-3]
        
        data = json.loads(clean_res.strip())
        profile = data.get("profile", "enterprise")
        complexity = int(data.get("complexity", 3))
        if profile not in ["enterprise", "sniper", "newsroom"]:
            profile = "enterprise"
        if complexity not in [1, 2, 3]:
            complexity = 3
        return profile, complexity
    except Exception as e:
        logging.error(f"Intent classification failed: {e}")
        
    # Fallback to heuristics
    lower_prompt = prompt.lower()
    if "essay" in lower_prompt or "blog" in lower_prompt or "post" in lower_prompt:
        return "newsroom", 2
    elif "script" in lower_prompt or "fix" in lower_prompt or "regex" in lower_prompt or "function" in lower_prompt:
        return "sniper", 1
    return "enterprise", 3

async def execute_live_swarm(websocket: WebSocket, message: str, models_dict: dict = None):
    try:
        # Light up origin
        await safe_send(websocket,{"event": "workflow_start", "message": message})
        await safe_send(websocket,{"event": "station_update", "station": "origin", "status": "active"})
        
        # Dispatch: classify and get token budget
        origin_model = normalize_models_dict(models_dict, 3).get("origin", "google/gemini-2.5-flash") if models_dict else "google/gemini-2.5-flash"
        profile, complexity = await classify_intent(message, origin_model)
        max_tokens = COMPLEXITY_BUDGETS[complexity]
        
        logging.info(f"[Dispatcher] Profile={profile}, Complexity={complexity}, MaxTokens={max_tokens}")
        
        await safe_send(websocket, {
            "event": "load_profile", 
            "profile": profile,
            "complexity": complexity,
            "message": f"🎯 Dispatcher → **{profile.upper()}** pipeline | Complexity {complexity}/3 | Token budget: {max_tokens:,}"
        })
        
        if profile == "sniper":
            await run_sniper_loop(websocket, message, normalize_models_dict(models_dict, complexity), max_tokens)
        elif profile == "newsroom":
            await run_newsroom_loop(websocket, message, normalize_models_dict(models_dict, complexity), max_tokens)
        else:
            await run_enterprise_loop(websocket, message, normalize_models_dict(models_dict, complexity), max_tokens)
            
    except asyncio.CancelledError:
        logging.info("Swarm execution cancelled by user")
    except Exception as e:
        logging.error(f"CRITICAL SWARM ERROR: {e}")
        await safe_send(websocket, {"event": "chat", "sender": "swarm", "text": f"CRITICAL CRASH: {str(e)}", "stage": "executor"})
        await safe_send(websocket, {"event": "workflow_complete"})
    finally:
        active_swarm_tasks.pop(websocket, None)

async def run_enterprise_loop(websocket: WebSocket, prompt: str, models: dict, max_tokens: int = 8192):

    # Let the UI reset state
    await safe_send(websocket,{"event": "workflow_start", "message": prompt})
    
    # Create artifacts directory
    import datetime
    run_timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir = f"_swarm_artifacts/{run_timestamp}"
    os.makedirs(os.path.join(fs_manager.workspace_path, artifact_dir), exist_ok=True)
    
    run_costs = {
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_cost_usd": 0.0,
        "stages": {}
    }

    def update_run_costs(stage_name: str, model_id: str, usage):
        payload = calculate_cost_payload(model_id, usage)
        if not payload: return
        
        run_costs["total_prompt_tokens"] += payload.get("prompt_tokens", 0)
        run_costs["total_completion_tokens"] += payload.get("completion_tokens", 0)
        run_costs["total_cost_usd"] += payload.get("total_cost_usd", 0.0)
        
        if stage_name not in run_costs["stages"]:
            run_costs["stages"][stage_name] = {"model": model_id, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
            
        run_costs["stages"][stage_name]["prompt_tokens"] += payload.get("prompt_tokens", 0)
        run_costs["stages"][stage_name]["completion_tokens"] += payload.get("completion_tokens", 0)
        run_costs["stages"][stage_name]["cost_usd"] += payload.get("total_cost_usd", 0.0)
        
        fs_manager.write_file(f"{artifact_dir}/cost_breakdown.json", json.dumps(run_costs, indent=2))
    
    # === Station 1: The Origin ===
    print("Starting station: origin")
    await safe_send(websocket,{
        "event": "station_update", 
        "station": "origin", 
        "status": "active"
    })
    
    # Broadcast the raw idea to chat
    await safe_send(websocket,{
        "event": "chat",
        "sender": "swarm",
        "text": f"Raw Idea Captured: {prompt}",
        "stage": "origin"
    })
    
    # Save Origin artifact
    fs_manager.write_file(f"{artifact_dir}/0_origin.md", prompt)
    files = fs_manager.list_files()
    await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
    
    # Complete origin
    await asyncio.sleep(0.5)
    await safe_send(websocket,{"event": "station_update", "station": "origin", "status": "complete"})
    
    # === Station 2: Spec Factory ===
    print("Starting station: specFactory")
    await safe_send(websocket,{
        "event": "station_update", 
        "station": "specFactory", 
        "status": "active"
    })
    
    # Send intermediate chat
    await safe_send(websocket,{
        "event": "chat",
        "sender": "swarm",
        "text": "Generating specifications via OpenRouter...",
        "stage": "specFactory"
    })
    
    try:
        # === Call OpenRouter API for Spec ===
        active_model = models.get("specFactory", "google/gemini-2.5-flash")
        sys_prompt = """You are the Chief Product Officer (Spec Factory). 
Your ONLY job is to write a comprehensive Product Requirements Document (PRD) in Markdown.
CRITICAL MANDATE: YOU ARE STRICTLY FORBIDDEN FROM WRITING ACTUAL CODE SYNTAX. 
You must define:
1. Core Purpose & Target Audience.
2. Comprehensive Feature Requirements.
3. Edge Cases & UX constraints.
4. Required dependencies and libraries.
5. Exact file structure required.
Do not write implementation details. Define the 'What' and the 'Why', never the 'How'."""
        
        spec, usage = await llm.generate(sys_prompt, f"ORIGINAL REQUEST:\n{prompt}", model_name=active_model)
        
        # Save Spec artifact
        fs_manager.write_file(f"{artifact_dir}/1_spec.md", spec)
        update_run_costs("1_specFactory", active_model, usage)
        files = fs_manager.list_files()
        await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
        
        # Broadcast the generated spec
        await safe_send(websocket,{
            "event": "chat",
            "sender": "swarm",
            "text": spec,
            "stage": "specFactory",
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "model": active_model
            }
        })
    except Exception as e:
        await safe_send(websocket,{
            "event": "chat",
            "sender": "swarm",
            "text": f"LLM Error: {str(e)}",
            "stage": "specFactory"
        })
        spec = f"Fallback Spec for: {prompt}"
    
    # Complete specFactory
    await safe_send(websocket,{"event": "station_update", "station": "specFactory", "status": "complete"})

    # === Station 2.5: OVERSEER ===
    logging.info("[Station 2.5] Starting station: overseer")
    await safe_send(websocket, {"event": "station_update", "station": "overseer", "status": "active"})
    await safe_send(websocket, {"event": "chat", "sender": "swarm", "text": "🧠 **Overseer** analysing PRD and creating Implementation Chunks...", "stage": "overseer"})

    overseer_data = {"chunks": []}
    overseer_model = models.get("overseer", "google/gemini-2.5-flash")
    try:
        overseer_sys = """You are the Overseer AI (Agile Product Manager).
Your job is to read the full Product Requirements Document (PRD) and break it down into sequential, manageable "Implementation Chunks" (Sprints).
Rule 1: Chunks MUST be strictly sequential. (e.g., Chunk 1: Database/Config. Chunk 2: Backend APIs. Chunk 3: Frontend UI).
Rule 2: Output strictly valid JSON.

Schema:
{
  "chunks": [
    {
      "chunk_id": 1,
      "title": "Core Data Models",
      "description": "Extracted specifications from the PRD relevant ONLY to this chunk. Be highly detailed."
    }
  ]
}"""
        overseer_user = f"FULL PRD:\n{spec}"
        overseer_raw, overseer_usage = await llm.generate(overseer_sys, overseer_user, model_name=overseer_model, is_json=True)
        update_run_costs("2_overseer", overseer_model, overseer_usage)

        # Strip markdown wrappers
        clean_overseer = overseer_raw.strip()
        if clean_overseer.startswith("```json"): clean_overseer = clean_overseer[7:]
        elif clean_overseer.startswith("```"): clean_overseer = clean_overseer[3:]
        if clean_overseer.endswith("```"): clean_overseer = clean_overseer[:-3]
        clean_overseer = clean_overseer.strip()

        overseer_data = json.loads(clean_overseer)
        fs_manager.write_file(f"{artifact_dir}/2_overseer_chunks.json", json.dumps(overseer_data, indent=2))

        chunk_count = len(overseer_data.get("chunks", []))
        await safe_send(websocket, {
            "event": "chat", "sender": "swarm",
            "text": f"✅ **Overseer** identified **{chunk_count} Implementation Chunk(s)**:\n" +
                    "\n".join(f"  {c['chunk_id']}. {c['title']}" for c in overseer_data.get("chunks", [])),
            "stage": "overseer",
            "usage": {"prompt_tokens": overseer_usage.prompt_tokens, "completion_tokens": overseer_usage.completion_tokens, "model": overseer_model}
        })
    except Exception as e:
        logging.error(f"[Overseer] Failed: {e}. Falling back to single chunk.")
        await safe_send(websocket, {"event": "chat", "sender": "swarm", "text": f"⚠️ Overseer failed ({str(e)}). Falling back to single-chunk execution.", "stage": "overseer"})
        overseer_data = {"chunks": [{"chunk_id": 1, "title": "Full Project", "description": spec}]}
        fs_manager.write_file(f"{artifact_dir}/2_overseer_chunks.json", json.dumps(overseer_data, indent=2))

    files = fs_manager.list_files()
    await safe_send(websocket, {"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
    await safe_send(websocket, {"event": "station_update", "station": "overseer", "status": "complete"})

    # Extract chunks list
    chunks = overseer_data.get("chunks", [])
    if not chunks:
        chunks = [{"chunk_id": 1, "title": "Full Project", "description": spec}]
    total_chunks = len(chunks)

    # Rolling architecture ledger path (relative to workspace)
    ledger_path = f"{artifact_dir}/global_architecture_ledger.md"
    fs_manager.write_file(ledger_path, f"# Global Architecture Ledger\n\nGenerated during swarm run: {artifact_dir}\n\n")

    # Helper: flatten file tree to a list of paths
    def flatten_files(node_list, path=""):
        res = []
        for item in node_list:
            full_path = path + item["name"]
            if item.get("is_dir"):
                res.extend(flatten_files(item.get("children", []), full_path + "/"))
            else:
                res.append(full_path)
        return res

    for index, chunk in enumerate(chunks):
        chunk_num = index + 1
        chunk_title = chunk.get("title", f"Chunk {chunk_num}")
        chunk_desc = chunk.get("description", "")
        
        # 1. Reset downstream UI for the new chunk
        await safe_send(websocket, {"event": "chunk_start", "chunk_title": chunk_title})
        
        # 2. Broadcast to Chat
        await safe_send(websocket, {
            "event": "chat", 
            "sender": "swarm", 
            "text": f"🔄 **[Overseer] Releasing Chunk {chunk_num}/{total_chunks}: {chunk_title}**\nFocus: {chunk_desc}", 
            "stage": "overseer"
        })

        # Dynamically read existing files into context
        existing_files = flatten_files(fs_manager.list_files())
        existing_files_str = "\n".join(existing_files) if existing_files else "No files exist currently."

        # Read the current Architecture Ledger
        try:
            ledger_content = fs_manager.read_file(ledger_path)
        except Exception:
            ledger_content = "No previous architecture defined."

        # === Station 3: PLANNER ===
        logging.info(f"[Station 3] Starting planner for chunk {chunk_num}")
        await safe_send(websocket,{"event": "station_update", "station": "planner", "status": "active"})
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"Planning architecture for Chunk {chunk_num} ({chunk_title})...", "stage": "planner"})
        
        try:
            active_model = models.get("planner", "google/gemini-2.5-flash")
            sys_prompt = f"""You are the Senior Systems Architect (Planner). 
You are planning architecture for CHUNK {chunk_num} of {total_chunks}.
Create a Topological Dependency Graph ONLY for the new files required in THIS chunk. Do not replan existing files.
CRITICAL MANDATE: DO NOT WRITE EXECUTABLE CODE. Use pseudo-code and architectural diagrams.

You must define:
1. Data Models and State Management.
2. Exact data flow between components.
3. API Contracts (Inputs, Outputs, and Types for every single function).

CRITICAL FINAL STEP: At the very end of your plan, you MUST output a strict JSON block wrapped in ```json containing the Topological Dependency Graph of the entire required codebase. This is MANDATORY.
Schema:
```json
{{"topological_graph": [{{"file_path": "backend/api.py", "description": "FastAPI routes", "depends_on": ["backend/models.py"]}}]}}
```
Every file that needs to be created must appear in this graph. Be exhaustive."""
            
            user_prompt = f"CHUNK DESCRIPTION Focus:\n{chunk_desc}\n\nEXISTING WORKSPACE FILES (Do not replan these):\n{existing_files_str}\n\nGLOBAL ARCHITECTURE SO FAR:\n{ledger_content}"
            
            plan, usage = await llm.generate(sys_prompt, user_prompt, model_name=active_model)
            
            fs_manager.write_file(f"{artifact_dir}/3_plan_chunk_{chunk_num}.md", plan)
            update_run_costs(f"3_planner_chunk_{chunk_num}", active_model, usage)
            
            await safe_send(websocket,{
                "event": "chat", "sender": "swarm", "text": plan, "stage": "planner", 
                "usage": {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens, "model": active_model}
            })
        except Exception as e:
            await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"Planner Error: {str(e)}", "stage": "planner"})
            plan = "Fallback Plan: Proceed to execution."
        
        await safe_send(websocket,{"event": "station_update", "station": "planner", "status": "complete"})

        # Extract Topological Graph from Planner output
        topological_graph = []
        topo_match = re.search(r'```json\s*(\{.*?\})\s*```', plan, re.DOTALL)
        if topo_match:
            try:
                topo_data = json.loads(topo_match.group(1))
                topological_graph = topo_data.get("topological_graph", [])
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse topological graph JSON: {e}")

        # === Station 3.5: COMMANDER AI ===
        logging.info(f"[Station 3.5] Starting commander for chunk {chunk_num}")
        await safe_send(websocket,{"event": "station_update", "station": "commander", "status": "active"})
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "Commander routing dependency graph to task forces...", "stage": "commander"})

        commander_model = None
        commander_usage = None
        routing = {"wizard_clusters": [], "specialist_pairs": [], "swarm_files": []}

        if topological_graph:
            try:
                commander_model = models.get("commander", "google/gemini-2.5-flash")
                commander_sys = """You are the Commander AI (Dynamic Execution Router).
Analyze the provided Topological Dependency Graph and assign EVERY file to a specific "Task Force" execution strategy based on code coupling.

STRATEGIES:
1. "wizard_clusters": Tightly coupled files (core logic, DB schemas, shared state). A single high-context model writes them together.
2. "specialist_pairs": API contracts (Producer/Consumer). Requires exactly two files (e.g., Backend Route + Frontend Hook) that must handshake perfectly.
3. "swarm_files": Isolated files with ZERO unwritten dependencies (UI components, utils, static docs). Generated in complete parallel.

Output strictly a valid JSON object matching this schema:
{
  "routing": {
    "wizard_clusters": [{"cluster_name": "Core System", "files": ["backend/main.py"]}],
    "specialist_pairs": [{"bridge_name": "User API Bridge", "producer": "backend/users.py", "consumer": "frontend/useUsers.ts"}],
    "swarm_files": ["README.md"]
  }
}"""
                commander_user = f"TOPOLOGICAL DEPENDENCY GRAPH:\n{json.dumps(topological_graph, indent=2)}"
                
                commander_raw, commander_usage = await llm.generate(
                    commander_sys, commander_user, model_name=commander_model, is_json=True
                )

                clean_commander = commander_raw.strip()
                if clean_commander.startswith("```json"): clean_commander = clean_commander[7:]
                elif clean_commander.startswith("```"): clean_commander = clean_commander[3:]
                if clean_commander.endswith("```"): clean_commander = clean_commander[:-3]

                commander_data = json.loads(clean_commander.strip())
                routing = commander_data.get("routing", routing)

                wizard_count = len(routing.get("wizard_clusters", []))
                specialist_count = len(routing.get("specialist_pairs", []))
                swarm_count = len(routing.get("swarm_files", []))

                summary = f"**Commander Routing Plan:**\n- 🧙 {wizard_count} Wizard Cluster(s)\n- 🤝 {specialist_count} Specialist Pair(s)\n- ⚡ {swarm_count} Swarm File(s)"
                await safe_send(websocket,{
                    "event": "chat", "sender": "swarm", "text": summary, "stage": "commander",
                    "usage": {"prompt_tokens": commander_usage.prompt_tokens, "completion_tokens": commander_usage.completion_tokens, "model": commander_model}
                })

            except Exception as e:
                logging.error(f"[Commander] Error: {e}. Using fallback routing.")
                await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"Commander routing failed ({str(e)}). Using fallback: single wizard cluster.", "stage": "commander"})
                all_files = [item["file_path"] for item in topological_graph if "file_path" in item]
                if all_files:
                    routing = {"wizard_clusters": [{"cluster_name": f"Fallback Cluster Chunk {chunk_num}", "files": all_files}], "specialist_pairs": [], "swarm_files": []}
        
        fs_manager.write_file(f"{artifact_dir}/3b_commander_routing_chunk_{chunk_num}.json", json.dumps(routing, indent=2))
        if commander_model and commander_usage:
            update_run_costs(f"4_commander_chunk_{chunk_num}", commander_model, commander_usage)
        await safe_send(websocket,{"event": "station_update", "station": "commander", "status": "complete"})

        # === Station 4: TRI-TIER EXECUTOR ===
        logging.info(f"[Station 4] Starting executor for chunk {chunk_num}")
        await safe_send(websocket,{"event": "station_update", "station": "executor", "status": "active"})
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"Executing parallel task forces for Chunk {chunk_num}...", "stage": "executor"})

        try:
            shared_context = f"""CURRENT WORKSPACE FILES:
{existing_files_str}

CHUNK FOCUS:
{chunk_desc}

ARCHITECT PLAN FOR THIS CHUNK:
{plan}

GLOBAL ARCHITECTURE SO FAR:
{ledger_content}
"""

            executor_cost_data = {"prompt_tokens": 0, "completion_tokens": 0, "total_cost_usd": 0.0, "models_used": []}

            def record_executor_cost(model: str, usage):
                payload = calculate_cost_payload(model, usage)
                if payload:
                    executor_cost_data["prompt_tokens"] += payload.get("prompt_tokens", 0)
                    executor_cost_data["completion_tokens"] += payload.get("completion_tokens", 0)
                    executor_cost_data["total_cost_usd"] += payload.get("total_cost_usd", 0.0)
                    if model not in executor_cost_data["models_used"]:
                        executor_cost_data["models_used"].append(model)

            async def execute_wizard(cluster: dict, context: str, model: str) -> list:
                cluster_name = cluster.get("cluster_name", "Unnamed Cluster")
                files_list_str = "\n".join(f"- {f}" for f in cluster.get("files", []))
                await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"🧙 Generating cluster: **{cluster_name}** ({len(cluster.get('files', []))} files)...", "stage": "executor"})

                wizard_sys = """You are the One-Shot Wizard. Write ALL files in this cluster simultaneously.
CRITICAL: Return ONLY a valid JSON object with this schema:
{"files": [{"path": "path/to/file.ext", "content": "raw file content here"}]}
DO NOT wrap in markdown."""
                wizard_user = f"{context}\n\nWRITE THESE FILES AS A CLUSTER:\n{files_list_str}"

                try:
                    raw, usage = await llm.generate(wizard_sys, wizard_user, model_name=model)
                    record_executor_cost(model, usage)
                    clean = raw.strip()
                    if clean.startswith("```json"): clean = clean[7:]
                    elif clean.startswith("```"): clean = clean[3:]
                    if clean.endswith("```"): clean = clean[:-3]
                    data = json.loads(clean.strip())
                    return data.get("files", [])
                except Exception as e:
                    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"⚠️ Cluster **{cluster_name}** failed: {str(e)}", "stage": "executor"})
                    return []

            async def execute_specialist(pair: dict, context: str, model: str) -> list:
                bridge_name = pair.get("bridge_name", "Unnamed Bridge")
                producer_path = pair.get("producer", "")
                consumer_path = pair.get("consumer", "")
                await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"🤝 Generating bridge: **{bridge_name}** ({producer_path} → {consumer_path})...", "stage": "executor"})

                producer_sys = """You are a Backend Specialist. Write ONLY this single file.
Return ONLY valid JSON: {"path": "path/to/file", "content": "file content"}
DO NOT wrap in markdown."""
                producer_user = f"{context}\n\nWRITE THIS PRODUCER FILE ONLY: {producer_path}"

                produced_code = ""
                result = []
                try:
                    raw, usage = await llm.generate(producer_sys, producer_user, model_name=model)
                    record_executor_cost(model, usage)
                    clean = raw.strip()
                    if clean.startswith("```json"): clean = clean[7:]
                    elif clean.startswith("```"): clean = clean[3:]
                    if clean.endswith("```"): clean = clean[:-3]
                    producer_data = json.loads(clean.strip())
                    produced_code = producer_data.get("content", "")
                    result.append({"path": producer_path, "content": produced_code})
                except Exception:
                    pass

                consumer_sys = """You are a Frontend Specialist. Write ONLY this single consumer file.
The backend generated its code. Match its API perfectly.
Return ONLY valid JSON: {"path": "path/to/file", "content": "file content"}
DO NOT wrap in markdown."""
                consumer_user = f"{context}\n\nBackend generated:\n\n```\n{produced_code}\n```\n\nWRITE CONSUMER FILE: {consumer_path}"

                try:
                    raw, usage = await llm.generate(consumer_sys, consumer_user, model_name=model)
                    record_executor_cost(model, usage)
                    clean = raw.strip()
                    if clean.startswith("```json"): clean = clean[7:]
                    elif clean.startswith("```"): clean = clean[3:]
                    if clean.endswith("```"): clean = clean[:-3]
                    consumer_data = json.loads(clean.strip())
                    result.append({"path": consumer_path, "content": consumer_data.get("content", "")})
                except Exception:
                    pass

                return result

            async def execute_swarm_worker(filepath: str, context: str, model: str) -> list:
                await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"⚡ Generating `{filepath}`...", "stage": "executor"})
                swarm_sys = """You are a Swarm Worker. Generate ONLY this single isolated file.
Return ONLY valid JSON: {"path": "path/to/file", "content": "file content"}
DO NOT wrap in markdown."""
                swarm_user = f"{context}\n\nGENERATE ONLY THIS FILE: {filepath}"
                try:
                    raw, usage = await llm.generate(swarm_sys, swarm_user, model_name=model)
                    record_executor_cost(model, usage)
                    clean = raw.strip()
                    if clean.startswith("```json"): clean = clean[7:]
                    elif clean.startswith("```"): clean = clean[3:]
                    if clean.endswith("```"): clean = clean[:-3]
                    data = json.loads(clean.strip())
                    return [{"path": data.get("path", filepath), "content": data.get("content", "")}]
                except Exception:
                    return []

            wizard_model = models.get("executorWizard", models.get("executor", "anthropic/claude-3.5-sonnet"))
            specialist_model = models.get("executorSpecialist", models.get("executor", "google/gemini-2.5-flash"))
            swarm_model = models.get("executorSwarm", models.get("executor", "anthropic/claude-3-haiku"))

            wizard_clusters = routing.get("wizard_clusters", [])
            specialist_pairs = routing.get("specialist_pairs", [])
            swarm_files = routing.get("swarm_files", [])

            if not wizard_clusters and not specialist_pairs and not swarm_files:
                legacy_model = models.get("executor", "anthropic/claude-3-haiku")
                legacy_sys = "You are the Senior Execution Drone. Return ONLY a valid JSON object: {\"files\": [{\"path\": \"...\", \"content\": \"...\"}]} DO NOT wrap in markdown."
                legacy_user = f"{shared_context}\n\n=========================================\nCRITICAL OUTPUT INSTRUCTIONS:\nReturn ONLY a valid JSON object without markdown wrappers.\n========================================="
                legacy_raw, usage = await llm.generate(legacy_sys, legacy_user, model_name=legacy_model)
                update_run_costs(f"4_executor_chunk_{chunk_num}", legacy_model, usage)
                clean_legacy = legacy_raw.strip()
                if clean_legacy.startswith("```json"): clean_legacy = clean_legacy[7:]
                elif clean_legacy.startswith("```"): clean_legacy = clean_legacy[3:]
                if clean_legacy.endswith("```"): clean_legacy = clean_legacy[:-3]
                try:
                    all_generated = json.loads(clean_legacy.strip()).get("files", [])
                except:
                    all_generated = []
            else:
                tasks = []
                for cluster in wizard_clusters: tasks.append(execute_wizard(cluster, shared_context, wizard_model))
                for pair in specialist_pairs: tasks.append(execute_specialist(pair, shared_context, specialist_model))
                for filepath in swarm_files: tasks.append(execute_swarm_worker(filepath, shared_context, swarm_model))

                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Add usage from parallel executions to the master cost ledger
                for used_model in executor_cost_data["models_used"]:
                    pseudo_usage = type('Usage', (), {'prompt_tokens': executor_cost_data['prompt_tokens'], 'completion_tokens': executor_cost_data['completion_tokens']})()
                    update_run_costs(f"4_executor_chunk_{chunk_num}_{used_model.split('/')[1]}", used_model, pseudo_usage)

                all_generated = []
                for res in results:
                    if isinstance(res, list): all_generated.extend(res)

            saved_files = []
            for file_obj in all_generated:
                path = file_obj.get("path", "").strip()
                content = file_obj.get("content", "")
                if path:
                    safe_path = path.lstrip("/")
                    full_path = f"{artifact_dir}/{safe_path}"
                    fs_manager.write_file(full_path, content)
                    saved_files.append(full_path)

            fs_manager.write_file(f"{artifact_dir}/4_executor_raw_chunk_{chunk_num}.json", json.dumps(all_generated, indent=2))

            summary_text = f"✅ **Execution Complete (Chunk {chunk_num})!**\n\nGenerated {len(saved_files)} file(s):\n" + "\n".join([f"- `{sf}`" for sf in saved_files])
            await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": summary_text, "stage": "executor"})
            
            # === Station 4.5: QA REVIEWER ===
            await safe_send(websocket,{"event": "station_update", "station": "qaReviewer", "status": "active"})
            await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"Reviewing Chunk {chunk_num} codebase...", "stage": "qaReviewer"})
            
            qa_model = models.get("qaReviewer", "google/gemini-2.5-flash")
            qa_sys_prompt = "You are the Lead QA Engineer. Review the generated codebase against the plan. Output a concise Markdown review document. Focus on architectural misses or bugs."
            codebase_context = ""
            for sf in saved_files:
                try:
                    content = fs_manager.read_file(sf)
                    codebase_context += f"\n--- {sf} ---\n{content}\n"
                except: pass
                
            qa_user_prompt = f"PLAN:\n{plan}\n\nGENERATED CODEBASE:\n{codebase_context}"
            qa_output, qa_usage = await llm.generate(qa_sys_prompt, qa_user_prompt, model_name=qa_model)
            
            fs_manager.write_file(f"{artifact_dir}/5_qa_review_chunk_{chunk_num}.md", qa_output)
            update_run_costs(f"5_qaReviewer_chunk_{chunk_num}", qa_model, qa_usage)
            await safe_send(websocket,{
                "event": "chat", "sender": "swarm", "text": qa_output, "stage": "qaReviewer",
                "usage": {"prompt_tokens": qa_usage.prompt_tokens, "completion_tokens": qa_usage.completion_tokens, "model": qa_model}
            })
            await safe_send(websocket,{"event": "station_update", "station": "qaReviewer", "status": "complete"})
            
            # --- THE LEDGER UPDATE (Post-QA) ---
            await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "📝 Updating Global Architecture Ledger before next chunk...", "stage": "qaReviewer"})
            ledger_summarizer_sys = """You are the Architecture Ledger Compiler.
Extract the strict API contracts, database schemas, and global state shapes from the provided code. 
Do not summarize the internal logic; ONLY outline the interfaces, exported functions, and data schemas so another agent can hook into them. Keep it extremely brief and high-signal."""
            
            ledger_summarizer_user = f"CODEBASE TO SUMMARIZE:\n{codebase_context}"
            # Use Haiku or Flash for fast summarization
            summarizer_model = models.get("qaReviewer", "google/gemini-2.5-flash")
            ledger_update, ledger_usage = await llm.generate(ledger_summarizer_sys, ledger_summarizer_user, model_name=summarizer_model)
            
            with open(os.path.join(fs_manager.workspace_path, ledger_path), "a", encoding="utf-8") as ledger_file:
                ledger_file.write(f"\n## Chunk {chunk_num} Updates\n{ledger_update}\n")
            
            update_run_costs(f"5b_ledger_update_chunk_{chunk_num}", summarizer_model, ledger_usage)

        except Exception as e:
            await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"Executor Error Chunk {chunk_num}: {str(e)}", "stage": "executor"})
        
        await safe_send(websocket,{"event": "station_update", "station": "executor", "status": "complete"})
        
        # End of current chunk loop iteration
        # Brief pause between chunks for UX
        await asyncio.sleep(1)

    # LOOP FINISHED.
    # Run DevOps Runner on the overall project state.
    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "Determining execution commands for full project...", "stage": "executor"})
    runner_sys_prompt = """You are the DevOps Runner.
Read the generated files and output the exact bash commands to install dependencies and run the main application.
Output EXACTLY a valid JSON object. DO NOT wrap the JSON in markdown code blocks.
Schema:
{
  "commands": [
    "pip3 install -r requirements.txt",
    "python3 app.py"
  ]
}"""

    # We read all files from the workspace as context for runner
    existing_files = flatten_files(fs_manager.list_files())
    runner_user_prompt = f"FULL GENERATED FILES:\n{existing_files}"
    
    runner_output, _ = await llm.generate(runner_sys_prompt, runner_user_prompt, model_name=models.get("executor", "anthropic/claude-3-haiku"), is_json=True)
    
    clean_runner_output = runner_output.strip()
    if clean_runner_output.startswith("```json"): clean_runner_output = clean_runner_output[7:]
    elif clean_runner_output.startswith("```"): clean_runner_output = clean_runner_output[3:]
    if clean_runner_output.endswith("```"): clean_runner_output = clean_runner_output[:-3]
    
    try:
        runner_data = json.loads(clean_runner_output.strip())
        commands = runner_data.get("commands", [])
    except Exception:
        commands = []
        
    if commands and active_pty_fds:
        cmd_str = " && ".join(commands) + "\n"
        for pty_fd in active_pty_fds:
            try:
                os.write(pty_fd, cmd_str.encode('utf-8'))
            except Exception:
                pass
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"Running in Local Terminal:\n\n`{cmd_str.strip()}`", "stage": "executor"})
    elif commands:
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"No active Local Terminal. Please run:\n\n`{' && '.join(commands)}`", "stage": "executor"})
        
    files_list = fs_manager.list_files()
    await safe_send(websocket,{"event": "file_list", "files": files_list, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
    await safe_send(websocket,{"event": "workflow_complete"})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    try:
        await websocket.accept()
        active_ws_connections.add(websocket)
        
        # Reload saved global workspace state
        state = load_ide_state()
        saved_workspace = state.get("last_workspace")
        if saved_workspace and os.path.isdir(saved_workspace):
            fs_manager.workspace_path = saved_workspace
    except Exception as e:
        print(f"WS Accept Error: {e}")
        return

    if "layout" in state:
        await safe_send(websocket,{"event": "layout_loaded", "layout": state["layout"], "chatAgentCompany": state.get("chatAgentCompany"), "chatAgentModel": state.get("chatAgentModel")})

    # Send initial file list
    files = fs_manager.list_files()
    await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
    
    # Try to load workspace-specific config automatically (DB or fallback file)
    config_data = get_workspace_config(fs_manager.workspace_path)
    if config_data:
        await safe_send(websocket,{"event": "config_loaded", "config": config_data})
        
    # Send models list immediately
    models = await fetch_openrouter_models()
    await safe_send(websocket, {"event": "models_list", "models": models})
    
    try:
        while True:
            data = await websocket.receive_json()
            command = data.get("command")
            
            if command == "list_files":
                files = fs_manager.list_files(data.get("path", ""))
                await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
                
            elif command == "get_models":
                models = await fetch_openrouter_models()
                await safe_send(websocket, {"event": "models_list", "models": models})
                
            elif command == "read_file":
                try:
                    content = fs_manager.read_file(data.get("path"))
                    await safe_send(websocket,{"event": "file_content", "path": data.get("path"), "content": content})
                except Exception as e:
                    await safe_send(websocket,{"event": "error", "message": str(e)})
                    
            elif command == "write_file":
                try:
                    fs_manager.write_file(data.get("path"), data.get("content"))
                    await safe_send(websocket,{"event": "file_written", "path": data.get("path")})
                    files = fs_manager.list_files()
                    await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
                except Exception as e:
                    await safe_send(websocket,{"event": "error", "message": str(e)})

            elif command == "set_workspace":
                new_path = data.get("path")
                if new_path and os.path.isdir(new_path):
                    fs_manager.workspace_path = os.path.abspath(new_path)
                    files = fs_manager.list_files()
                    
                    # Update global observer path
                    try:
                        global_observer.unschedule_all()
                        global_observer.schedule(global_watcher, fs_manager.workspace_path, recursive=True)
                    except Exception:
                        pass
                    
                    # Persist global state
                    state["last_workspace"] = fs_manager.workspace_path
                    save_ide_state(state)
                    
                    await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
                    
                    # Re-load config from new workspace
                    config_data = get_workspace_config(fs_manager.workspace_path)
                    if config_data:
                        await safe_send(websocket,{"event": "config_loaded", "config": config_data})
                else:
                    await safe_send(websocket,{"event": "error", "message": "Invalid directory path"})

            elif command == "save_layout":
                state["layout"] = data.get("layout", state.get("layout", {}))
                if "chatAgentCompany" in data:
                    state["chatAgentCompany"] = data["chatAgentCompany"]
                if "chatAgentModel" in data:
                    state["chatAgentModel"] = data["chatAgentModel"]
                save_ide_state(state)

            elif command == "save_config":
                try:
                    config_data = data.get("config", {})
                    save_workspace_config(fs_manager.workspace_path, config_data)
                    
                    if "chatAgentCompany" in data:
                        state["chatAgentCompany"] = data["chatAgentCompany"]
                    if "chatAgentModel" in data:
                        state["chatAgentModel"] = data["chatAgentModel"]
                    save_ide_state(state)
                    
                    files = fs_manager.list_files()
                    await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
                except Exception as e:
                    await safe_send(websocket,{"event": "error", "message": f"Failed to save config: {str(e)}"})

            elif command == "load_config":
                try:
                    config_data = get_workspace_config(fs_manager.workspace_path)
                    if config_data:
                        await safe_send(websocket,{"event": "config_loaded", "config": config_data})
                        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "Configuration loaded from workspace.", "stage": "origin"})
                    else:
                        await safe_send(websocket,{"event": "error", "message": "No swarm_config.json found in the current workspace/DB."})
                except Exception as e:
                    await safe_send(websocket,{"event": "error", "message": f"Failed to load config: {str(e)}"})

            elif command == "preview_swarm":
                # Classification-only: show which profile/nodes will be used, don't execute
                msg = data.get("message", "")
                models_dict = data.get("models", {})
                origin_model = normalize_models_dict(models_dict, 3).get("origin", "google/gemini-2.5-flash")
                try:
                    await safe_send(websocket, {"event": "station_update", "station": "origin", "status": "active"})
                    profile, complexity = await classify_intent(msg, origin_model)
                    max_tokens = COMPLEXITY_BUDGETS[complexity]
                    await safe_send(websocket, {"event": "station_update", "station": "origin", "status": "complete"})
                    await safe_send(websocket, {
                        "event": "load_profile",
                        "profile": profile,
                        "complexity": complexity,
                        "message": f"🔍 **Preview:** Dispatcher selected **{profile.upper()}** pipeline | Complexity {complexity}/3 | Token budget: {max_tokens:,}\n\nClick **Run Swarm** to execute."
                    })
                    await safe_send(websocket, {"event": "preview_ready", "profile": profile, "complexity": complexity})
                except Exception as e:
                    await safe_send(websocket, {"event": "load_profile", "profile": "enterprise", "complexity": 3,
                        "message": f"⚠️ Preview failed ({e}), defaulting to Enterprise."})
                    await safe_send(websocket, {"event": "preview_ready", "profile": "enterprise", "complexity": 3})

            elif command == "swarm_message":
                msg = data.get("message", "Build something")
                models_dict = data.get("models", {})
                
                # Cancel any existing task for this websocket before starting a new one
                old_task = active_swarm_tasks.get(websocket)
                if old_task and not old_task.done():
                    old_task.cancel()
                    
                task = asyncio.create_task(execute_live_swarm(websocket, msg, models_dict))
                active_swarm_tasks[websocket] = task

            elif command == "kill_swarm":
                task = active_swarm_tasks.get(websocket)
                if task and not task.done():
                    task.cancel()
                    await safe_send(websocket, {"event": "chat", "sender": "swarm", "text": "🛑 **Swarm execution forcefully terminated by user.**", "stage": "executor"})
                    await safe_send(websocket, {"event": "workflow_complete"})
                    active_swarm_tasks.pop(websocket, None)

            elif command == "chat_message":
                msg = data.get("message", "")
                model = data.get("model", "google/gemini-2.5-flash")
                history = data.get("history", [])
                models_dict = data.get("models", {})
                asyncio.create_task(execute_agent_chat(websocket, msg, model, history, fs_manager, models_dict))

            elif command == "rename_file":
                try:
                    old_path = fs_manager._get_safe_path(data.get("old_path", ""))
                    new_name = data.get("new_name", "").strip()
                    if not new_name or "/" in new_name or "\\" in new_name:
                        raise ValueError("Invalid new name")
                    new_path = os.path.join(os.path.dirname(old_path), new_name)
                    new_path_safe = fs_manager._get_safe_path(os.path.relpath(new_path, fs_manager.workspace_path))
                    os.rename(old_path, new_path_safe)
                    files = fs_manager.list_files()
                    await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path)})
                except Exception as e:
                    await safe_send(websocket,{"event": "error", "message": f"Rename failed: {str(e)}"})

            elif command == "delete_file":
                try:
                    import shutil
                    target_path = fs_manager._get_safe_path(data.get("path", ""))
                    if os.path.isdir(target_path):
                        shutil.rmtree(target_path)
                    else:
                        os.remove(target_path)
                    files = fs_manager.list_files()
                    await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path)})
                except Exception as e:
                    await safe_send(websocket,{"event": "error", "message": f"Delete failed: {str(e)}"})

            elif command == "reveal_in_finder":
                try:
                    target_path = fs_manager._get_safe_path(data.get("path", ""))
                    # Use the directory if it's a file
                    reveal_path = target_path if os.path.isdir(target_path) else os.path.dirname(target_path)
                    import subprocess
                    subprocess.Popen(["open", "-R", target_path])
                except Exception as e:
                    await safe_send(websocket,{"event": "error", "message": f"Reveal failed: {str(e)}"})

    except WebSocketDisconnect:
        print("Client disconnected")
    finally:
        if websocket in active_ws_connections:
            active_ws_connections.remove(websocket)

@app.websocket("/pty")
async def pty_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    import pty
    import os
    import fcntl
    import signal
    import asyncio
    
    pid, fd = pty.fork()
    active_pty_fds.add(fd)
    
    if pid == 0:
        os.chdir(fs_manager.workspace_path)
        os.environ["PWD"] = fs_manager.workspace_path
        shell = os.environ.get("SHELL", "/bin/sh")
        os.environ["TERM"] = "xterm-256color"
        try:
            # We want to start a login shell so it loads user rc files correctly
            os.execv(shell, [shell, "-l"])
        except Exception as e:
            print("Failed to spawn shell", e)
            os._exit(1)
    else:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
        async def read_from_pty():
            while True:
                try:
                    data = os.read(fd, 8192)
                    if data:
                        await websocket.send_bytes(data)
                except BlockingIOError:
                    await asyncio.sleep(0.01)
                except Exception:
                    break

        async def read_from_ws():
            import json
            import struct
            import termios
            try:
                while True:
                    raw_data = await websocket.receive_text()
                    try:
                        msg = json.loads(raw_data)
                        if msg.get("type") == "resize":
                            rows = int(msg.get("rows", 24))
                            cols = int(msg.get("cols", 80))
                            winsize = struct.pack("HHHH", rows, cols, 0, 0)
                            fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
                        elif msg.get("type") == "input":
                            os.write(fd, msg.get("data", "").encode('utf-8'))
                    except json.JSONDecodeError:
                        # Fallback for purely raw text
                        os.write(fd, raw_data.encode('utf-8'))
            except Exception as e:
                print(f"WS read error: {e}")

        try:
            done, pending = await asyncio.wait(
                [asyncio.create_task(read_from_pty()), asyncio.create_task(read_from_ws())],
                return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
        except (asyncio.CancelledError, WebSocketDisconnect, Exception):
            pass
        finally:
            active_pty_fds.discard(fd)
            # CRITICAL: Prevent Zombie Processes
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                os.close(fd)
            except Exception as e:
                print(f"Cleanup error for PTY {pid}: {e}")

async def run_sniper_loop(websocket: WebSocket, prompt: str, models: dict, max_tokens: int = 3072):
    # Let the UI reset state
    await safe_send(websocket,{"event": "workflow_start", "message": prompt})
    
    import datetime
    run_timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir = f"_swarm_artifacts/{run_timestamp}"
    os.makedirs(os.path.join(fs_manager.workspace_path, artifact_dir), exist_ok=True)
    
    run_costs = {"total_prompt_tokens": 0, "total_completion_tokens": 0, "total_cost_usd": 0.0, "stages": {}}

    def update_run_costs(stage_name: str, model_id: str, usage):
        payload = calculate_cost_payload(model_id, usage)
        if not payload: return
        run_costs["total_prompt_tokens"] += payload.get("prompt_tokens", 0)
        run_costs["total_completion_tokens"] += payload.get("completion_tokens", 0)
        run_costs["total_cost_usd"] += payload.get("total_cost_usd", 0.0)
        if stage_name not in run_costs["stages"]: run_costs["stages"][stage_name] = {"model": model_id, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        run_costs["stages"][stage_name]["prompt_tokens"] += payload.get("prompt_tokens", 0)
        run_costs["stages"][stage_name]["completion_tokens"] += payload.get("completion_tokens", 0)
        run_costs["stages"][stage_name]["cost_usd"] += payload.get("total_cost_usd", 0.0)
        fs_manager.write_file(f"{artifact_dir}/cost_breakdown.json", json.dumps(run_costs, indent=2))

    # --- Origin ---
    await safe_send(websocket,{"event": "station_update", "station": "origin", "status": "active"})
    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"🎯 **Sniper Lock-on:** {prompt}", "stage": "origin"})
    fs_manager.write_file(f"{artifact_dir}/0_origin.md", prompt)
    files = fs_manager.list_files()
    await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path)})
    await asyncio.sleep(0.5)
    await safe_send(websocket,{"event": "station_update", "station": "origin", "status": "complete"})

    # --- Wizard (Executor) ---
    await safe_send(websocket,{"event": "station_update", "station": "executor", "status": "active"})
    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "🧙 One-Shot Wizard generating file...", "stage": "executor"})
    
    wizard_sys = """You are the One-Shot Wizard. Write ONLY the code needed to solve this.
CRITICAL: Return ONLY a valid JSON object with this schema:
{"files": [{"path": "relative/file/path.py", "content": "raw code string"}]}"""
    wizard_user = f"EXISTING FILES:\n{fs_manager.format_all_files()}\n\nTARGET SCRIPT:\n{prompt}"
    
    wizard_model = models.get("executorWizard", "google/gemini-2.5-flash")
    raw_res = ""
    try:
        raw_res, usage = await llm.generate(wizard_sys, wizard_user, model_name=wizard_model)
        update_run_costs("executor_wizard", wizard_model, usage)
        
        clean = raw_res.strip()
        if clean.startswith("```json"): clean = clean[7:]
        elif clean.startswith("```"): clean = clean[3:]
        if clean.endswith("```"): clean = clean[:-3]
        
        data = json.loads(clean.strip())
        files_to_write = data.get("files", [])
        
        for f in files_to_write:
            fpath = f.get("path")
            fcontent = f.get("content")
            if fpath and fcontent:
                fs_manager.write_file(fpath, fcontent)
                await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"✨ Created/Updated: `{fpath}`", "stage": "executor"})
        
    except Exception as e:
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"⚠️ Wizard Error: {e}", "stage": "executor"})
        
    fs_manager.write_file(f"{artifact_dir}/1_wizard.md", raw_res)
    files = fs_manager.list_files()
    await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path)})
    await safe_send(websocket,{"event": "station_update", "station": "executor", "status": "complete"})
    
    # --- QA Reviewer ---
    await safe_send(websocket,{"event": "station_update", "station": "qaReviewer", "status": "active"})
    qa_sys = """You are the Code Reviewer. Analyze the generated script for syntax errors, missing imports, or obvious logic bugs. Output markdown text only."""
    qa_user = f"USER REQUEST: {prompt}\n\nWIZARD OUTPUT:\n{raw_res}"
    qa_model = models.get("qaReviewer", "google/gemini-2.5-flash")
    
    try:
        qa_res, qa_usage = await llm.generate(qa_sys, qa_user, model_name=qa_model)
        update_run_costs("qa_reviewer", qa_model, qa_usage)
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"**QA Review:**\n{qa_res}", "stage": "qaReviewer"})
        fs_manager.write_file(f"{artifact_dir}/2_qa.md", qa_res)
        # Broadcast file list after QA writes its file
        files = fs_manager.list_files()
        await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path)})
    except Exception as e:
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"⚠️ QA Error: {e}", "stage": "qaReviewer"})
        
    await safe_send(websocket,{"event": "station_update", "station": "qaReviewer", "status": "complete"})
    
    run_costs["total_cost_usd"] = round(run_costs["total_cost_usd"], 5)
    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"📊 **Workflow Complete.**\nTarget Eliminated.\nCost: ${run_costs['total_cost_usd']}", "stage": "origin"})
    # Final authoritative file list broadcast before completing
    files = fs_manager.list_files()
    await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path)})
    await safe_send(websocket,{"event": "workflow_complete"})


async def run_newsroom_loop(websocket: WebSocket, prompt: str, models: dict, max_tokens: int = 3072):
    # Let the UI reset state
    await safe_send(websocket,{"event": "workflow_start", "message": prompt})
    
    import datetime
    run_timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir = f"_swarm_artifacts/{run_timestamp}"
    os.makedirs(os.path.join(fs_manager.workspace_path, artifact_dir), exist_ok=True)
    
    run_costs = {"total_prompt_tokens": 0, "total_completion_tokens": 0, "total_cost_usd": 0.0, "stages": {}}

    def update_run_costs(stage_name: str, model_id: str, usage):
        payload = calculate_cost_payload(model_id, usage)
        if not payload: return
        run_costs["total_prompt_tokens"] += payload.get("prompt_tokens", 0)
        run_costs["total_completion_tokens"] += payload.get("completion_tokens", 0)
        run_costs["total_cost_usd"] += payload.get("total_cost_usd", 0.0)
        if stage_name not in run_costs["stages"]: run_costs["stages"][stage_name] = {"model": model_id, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        run_costs["stages"][stage_name]["prompt_tokens"] += payload.get("prompt_tokens", 0)
        run_costs["stages"][stage_name]["completion_tokens"] += payload.get("completion_tokens", 0)
        run_costs["stages"][stage_name]["cost_usd"] += payload.get("total_cost_usd", 0.0)
        fs_manager.write_file(f"{artifact_dir}/cost_breakdown.json", json.dumps(run_costs, indent=2))

    # --- Origin ---
    await safe_send(websocket,{"event": "station_update", "station": "origin", "status": "active"})
    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"📰 **Newsroom Subject:** {prompt}", "stage": "origin"})
    fs_manager.write_file(f"{artifact_dir}/0_topic.md", prompt)
    files = fs_manager.list_files()
    await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path)})
    await asyncio.sleep(0.5)
    await safe_send(websocket,{"event": "station_update", "station": "origin", "status": "complete"})

    # --- Editor in Chief (SpecFactory node mapped) ---
    await safe_send(websocket,{"event": "station_update", "station": "specFactory", "status": "active"})
    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "👓 Editor-in-Chief structuring outline...", "stage": "specFactory"})
    
    editor_sys = """You are the Editor-in-Chief. You receive a topic. 
Write a highly detailed outline and creative brief for the writer. DO NOT WRITE THE ESSAY. Just the sections, tone, and key points."""
    editor_model = models.get("specFactory", "google/gemini-2.5-flash")
    
    editor_res = ""
    try:
        editor_res, usage = await llm.generate(editor_sys, prompt, model_name=editor_model)
        update_run_costs("editor", editor_model, usage)
        fs_manager.write_file(f"{artifact_dir}/1_outline.md", editor_res)
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"**Outline Approved:**\n{editor_res}", "stage": "specFactory"})
    except Exception as e:
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"⚠️ Editor Error: {e}", "stage": "specFactory"})
    
    await safe_send(websocket,{"event": "station_update", "station": "specFactory", "status": "complete"})
    
    # --- Prose Writer (Executor node mapped) ---
    await safe_send(websocket,{"event": "station_update", "station": "executor", "status": "active"})
    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "✍️ Writer drafting content...", "stage": "executor"})
    
    writer_sys = "You are the Prose Writer. Follow the Editor's outline exactly and write the complete, full-length content in Markdown format. Be beautifully creative and articulate. Under NO CIRCUMSTANCES write JSON or code architectures."
    writer_user = f"TOPIC: {prompt}\n\nEDITOR OUTLINE:\n{editor_res}"
    writer_model = models.get("executorWizard", "google/gemini-2.5-flash")
    
    writer_res = ""
    try:
        writer_res, usage = await llm.generate(writer_sys, writer_user, model_name=writer_model)
        update_run_costs("writer", writer_model, usage)
        
        # Save payload as a markdown file 
        safe_title = "".join(c if c.isalnum() else "_" for c in prompt[:20]).strip("_").lower()
        if not safe_title: safe_title = "draft"
        filepath = f"{safe_title}.md"
        fs_manager.write_file(filepath, writer_res)
        fs_manager.write_file(f"{artifact_dir}/2_draft_output.md", writer_res)
        
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"✒️ Content saved to `{filepath}`", "stage": "executor"})
        files = fs_manager.list_files()
        await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path)})
    except Exception as e:
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"⚠️ Writer Error: {e}", "stage": "executor"})
        
    await safe_send(websocket,{"event": "station_update", "station": "executor", "status": "complete"})
    
    # --- Copy Editor (QA node mapped) ---
    await safe_send(websocket,{"event": "station_update", "station": "qaReviewer", "status": "active"})
    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "🔍 Copy Editor reviewing draft...", "stage": "qaReviewer"})
    
    qa_sys = "You are the Copy Editor. Review the draft for tone, grammar, and alignment with the outline. Provide constructive feedback points. Output markdown."
    qa_user = f"OUTLINE: {editor_res}\n\nDRAFT:\n{writer_res}"
    qa_model = models.get("qaReviewer", "google/gemini-2.5-flash")
    
    try:
        qa_res, usage = await llm.generate(qa_sys, qa_user, model_name=qa_model)
        update_run_costs("copy_editor", qa_model, usage)
        fs_manager.write_file(f"{artifact_dir}/3_copy_edits.md", qa_res)
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"**Review Notes:**\n{qa_res}", "stage": "qaReviewer"})
        # Broadcast file list after copy editor writes its file
        files = fs_manager.list_files()
        await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path)})
    except Exception as e:
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"⚠️ Copy Editor Error: {e}", "stage": "qaReviewer"})

    await safe_send(websocket,{"event": "station_update", "station": "qaReviewer", "status": "complete"})

    run_costs["total_cost_usd"] = round(run_costs["total_cost_usd"], 5)
    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"📰 **Publishing Complete.**\nCost: ${run_costs['total_cost_usd']}", "stage": "origin"})
    # Final authoritative file list broadcast before completing
    files = fs_manager.list_files()
    await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path)})
    await safe_send(websocket,{"event": "workflow_complete"})


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=6500, reload=False)
