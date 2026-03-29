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

load_dotenv(".env.local")

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

    async def generate(self, system_prompt: str, user_prompt: str, model_name: str = "google/gemini-2.5-flash", is_json: bool = False) -> tuple[str, any]:
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
            "max_tokens": 8192,
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

async def fetch_openrouter_models():
    global cached_models
    if cached_models:
        return cached_models
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}"}
            )
            if resp.status_code == 200:
                data = resp.json()
                if "data" in data:
                    sorted_data = sorted(data["data"], key=lambda x: x.get("name", "").lower())
                    cached_models = sorted_data
                    return cached_models
    except Exception as e:
        print(f"Failed to fetch models via backend proxy: {e}")
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
from watchdog.observers import Observer
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

WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../workspace_sandbox"))
_initial_state = load_ide_state()
_saved_workspace = _initial_state.get("last_workspace")
if _saved_workspace and os.path.isdir(_saved_workspace):
    WORKSPACE_DIR = _saved_workspace

fs_manager = FileSystemManager(WORKSPACE_DIR)

global_observer.schedule(global_watcher, fs_manager.workspace_path, recursive=True)
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

async def execute_live_swarm(websocket: WebSocket, message: str, models_dict: dict = None):
    try:
        await _execute_live_swarm_logic(websocket, message, models_dict)
    except Exception as e:
        logging.error(f"CRITICAL SWARM ERROR: {e}")
        await safe_send(websocket, {"event": "chat", "sender": "swarm", "text": f"CRITICAL CRASH: {str(e)}", "stage": "executor"})
        await safe_send(websocket, {"event": "workflow_complete"})

async def _execute_live_swarm_logic(websocket: WebSocket, prompt: str, models: dict):

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
    
    # === Station 3: PLANNER ===
    logging.info("[Station 3] Starting station: planner")
    print("Starting station: planner")
    await safe_send(websocket,{"event": "station_update", "station": "planner", "status": "active"})
    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "Planning architecture and layout...", "stage": "planner"})
    try:
        active_model = models.get("planner", "google/gemini-2.5-flash")
        logging.info(f"[Station 3] Using planner model: {active_model}")
        sys_prompt = """You are the Senior Systems Architect (Planner). 
Take the PRD and write an exhaustive, function-by-function architectural plan in Markdown.
CRITICAL MANDATE: DO NOT WRITE EXECUTABLE CODE. You must use pseudo-code and architectural diagrams.
You must define:
1. Data Models and State Management.
2. Exact data flow between components.
3. API Contracts (Inputs, Outputs, and Types for every single function).
4. Step-by-step logic for complex algorithms.
Ensure the logic handles the edge cases defined in the PRD.

CRITICAL FINAL STEP: At the very end of your plan, you MUST output a strict JSON block wrapped in ```json containing the Topological Dependency Graph of the entire required codebase. This is MANDATORY.
Schema:
```json
{"topological_graph": [{"file_path": "backend/api.py", "description": "FastAPI routes", "depends_on": ["backend/models.py"]}]}
```
Every file that needs to be created must appear in this graph. Files with no dependencies should have an empty depends_on list. Be exhaustive."""
        
        # Accumulate payload
        user_prompt = f"ORIGINAL REQUEST:\n{prompt}\n\nSPEC (PRD):\n{spec}"
        
        plan, usage = await llm.generate(sys_prompt, user_prompt, model_name=active_model)
        
        # Save Planner artifact
        fs_manager.write_file(f"{artifact_dir}/2_plan.md", plan)
        update_run_costs("2_planner", active_model, usage)
        files = fs_manager.list_files()
        await safe_send(websocket,{"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
        
        await safe_send(websocket,{
            "event": "chat", "sender": "swarm", "text": plan, "stage": "planner", 
            "usage": {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens, "model": active_model}
        })
    except Exception as e:
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"Planner Error: {str(e)}", "stage": "planner"})
        plan = "Fallback Plan: Proceed to execution."
    await safe_send(websocket,{"event": "station_update", "station": "planner", "status": "complete"})

    # === Extract Topological Graph from Planner output ===
    logging.info("[Station 3] Extracting Topological Graph")
    topological_graph = []
    topo_match = re.search(r'```json\s*(\{.*?\})\s*```', plan, re.DOTALL)
    if topo_match:
        try:
            topo_data = json.loads(topo_match.group(1))
            topological_graph = topo_data.get("topological_graph", [])
            logging.info(f"[Commander] Extracted topological graph with {len(topological_graph)} files.")
            print(f"[Commander] Extracted topological graph with {len(topological_graph)} files.")
        except json.JSONDecodeError as e:
            logging.error(f"[Commander] Failed to parse topological graph JSON: {e}")
            print("[Commander] Failed to parse topological graph JSON.")
    else:
        logging.warning("[Commander] No topological graph found in planner output — will use fallback.")
        print("[Commander] No topological graph found in planner output — will use fallback.")

    # === Station 3.5: COMMANDER AI ===
    logging.info("[Station 3.5] Starting station: commander")
    print("Starting station: commander")
    await safe_send(websocket,{"event": "station_update", "station": "commander", "status": "active"})
    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "Commander AI analyzing dependency graph and routing files to task forces...", "stage": "commander"})

    commander_model = None
    commander_usage = None
    routing = {"wizard_clusters": [], "specialist_pairs": [], "swarm_files": []}

    if topological_graph:
        logging.info("[Station 3.5] Topological graph found, generating routing")
        try:
            commander_model = models.get("commander", "google/gemini-2.5-flash")
            commander_sys = """You are the Commander AI (Dynamic Execution Router).
Analyze the provided Topological Dependency Graph and assign EVERY file to a specific "Task Force" execution strategy based on code coupling.

STRATEGIES:
1. "wizard_clusters": Tightly coupled files (core logic, DB schemas, shared state). A single high-context model writes them together.
2. "specialist_pairs": API contracts (Producer/Consumer). Requires exactly two files (e.g., Backend Route + Frontend Hook) that must handshake perfectly.
3. "swarm_files": Isolated files with ZERO unwritten dependencies (UI components, utils, static docs). Generated in complete parallel.

RULES:
- EVERY file from the graph MUST be assigned to exactly ONE strategy.
- You can create multiple wizard_clusters if there are separate highly-coupled systems.
- specialist_pairs must have exactly one "producer" and one "consumer".

Output strictly a valid JSON object matching this schema:
{
  "routing": {
    "wizard_clusters": [
      {
        "cluster_name": "Core System",
        "files": ["backend/main.py", "backend/models.py"]
      }
    ],
    "specialist_pairs": [
      {
        "bridge_name": "User API Bridge",
        "producer": "backend/api/users.py",
        "consumer": "frontend/hooks/useUsers.ts"
      }
    ],
    "swarm_files": [
      "frontend/components/Button.tsx",
      "README.md"
    ]
  }
}"""
            commander_user = f"TOPOLOGICAL DEPENDENCY GRAPH:\n{json.dumps(topological_graph, indent=2)}"
            
            logging.info(f"[Station 3.5] Calling LLM with model {commander_model}")
            commander_raw, commander_usage = await llm.generate(
                commander_sys, commander_user, model_name=commander_model, is_json=True
            )
            logging.info(f"[Station 3.5] LLM generation success. Raw response length: {len(commander_raw)}")

            # Strip any markdown wrappers
            clean_commander = commander_raw.strip()
            if clean_commander.startswith("```json"): clean_commander = clean_commander[7:]
            elif clean_commander.startswith("```"): clean_commander = clean_commander[3:]
            if clean_commander.endswith("```"): clean_commander = clean_commander[:-3]
            clean_commander = clean_commander.strip()

            commander_data = json.loads(clean_commander)
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
            print(f"[Commander] Error: {e}. Using fallback routing.")
            await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"Commander routing failed ({str(e)}). Using fallback: single wizard cluster.", "stage": "commander"})
            # Fallback: dump everything into one wizard cluster
            all_files = [item["file_path"] for item in topological_graph if "file_path" in item]
            if all_files:
                routing = {"wizard_clusters": [{"cluster_name": "Fallback Cluster", "files": all_files}], "specialist_pairs": [], "swarm_files": []}
    else:
        # No graph at all — Commander will pass through; Executor will be full-context
        logging.info("[Station 3.5] No dependency graph available handling pass-through")
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "No dependency graph available. Commander delegating full-context generation to Wizard.", "stage": "commander"})

    # Save commander routing artifact
    logging.info("[Station 3.5] Saving commander routing artifact")
    fs_manager.write_file(f"{artifact_dir}/2b_commander_routing.json", json.dumps(routing, indent=2))
    if commander_model and commander_usage:
        update_run_costs("2b_commander", commander_model, commander_usage)
    files_list = fs_manager.list_files()
    await safe_send(websocket,{"event": "file_list", "files": files_list, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
    await safe_send(websocket,{"event": "station_update", "station": "commander", "status": "complete"})

    # === Station 4: TRI-TIER EXECUTOR ===
    logging.info("[Station 4] Starting station: executor")
    print("Starting station: executor")
    await safe_send(websocket,{"event": "station_update", "station": "executor", "status": "active"})
    await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "Commander deployed. Executing parallel task forces...", "stage": "executor"})

    try:
        # Build shared context
        def flatten_files(node_list, path=""):
            res = []
            for item in node_list:
                full_path = path + item["name"]
                if item.get("is_dir"):
                    res.extend(flatten_files(item.get("children", []), full_path + "/"))
                else:
                    res.append(full_path)
            return res

        existing_files = flatten_files(fs_manager.list_files())
        existing_files_str = "\n".join(existing_files) if existing_files else "No files exist currently."

        shared_context = f"""CURRENT WORKSPACE FILES:
{existing_files_str}

ORIGINAL REQUEST:
{prompt}

SPEC (PRD):
{spec}

ARCHITECT PLAN:
{plan}"""

        executor_cost_data = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_cost_usd": 0.0,
            "models_used": []
        }

        def record_executor_cost(model: str, usage):
            payload = calculate_cost_payload(model, usage)
            if payload:
                executor_cost_data["prompt_tokens"] += payload.get("prompt_tokens", 0)
                executor_cost_data["completion_tokens"] += payload.get("completion_tokens", 0)
                executor_cost_data["total_cost_usd"] += payload.get("total_cost_usd", 0.0)
                if model not in executor_cost_data["models_used"]:
                    executor_cost_data["models_used"].append(model)

        # ---- Sub-Routine A: Wizard (tight-coupling, multi-file) ----
        async def execute_wizard(cluster: dict, context: str, model: str) -> list:
            cluster_name = cluster.get("cluster_name", "Unnamed Cluster")
            files_list_str = "\n".join(f"- {f}" for f in cluster.get("files", []))
            await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"🧙 [Wizard] Generating cluster: **{cluster_name}** ({len(cluster.get('files', []))} files)...", "stage": "executor"})

            wizard_sys = """You are the One-Shot Wizard (High-Context Code Generator).
You will write ALL files in this cluster simultaneously with full shared context.
CRITICAL: Return ONLY a valid JSON object with this schema:
{"files": [{"path": "path/to/file.ext", "content": "raw file content here"}]}
DO NOT wrap in markdown. DO NOT add any explanations."""
            wizard_user = f"{context}\n\nWRITE THESE FILES AS A CLUSTER (they are tightly coupled):\n{files_list_str}"

            try:
                raw, usage = await llm.generate(wizard_sys, wizard_user, model_name=model)
                record_executor_cost(model, usage)
                clean = raw.strip()
                if clean.startswith("```json"): clean = clean[7:]
                elif clean.startswith("```"): clean = clean[3:]
                if clean.endswith("```"): clean = clean[:-3]
                data = json.loads(clean.strip())
                result = data.get("files", [])
                await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"✅ [Wizard] Cluster **{cluster_name}** complete: {len(result)} file(s) generated.", "stage": "executor"})
                return result
            except Exception as e:
                await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"⚠️ [Wizard] Cluster **{cluster_name}** failed: {str(e)}", "stage": "executor"})
                return []

        # ---- Sub-Routine B: Specialist (producer → consumer ping-pong) ----
        async def execute_specialist(pair: dict, context: str, model: str) -> list:
            bridge_name = pair.get("bridge_name", "Unnamed Bridge")
            producer_path = pair.get("producer", "")
            consumer_path = pair.get("consumer", "")
            await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"🤝 [Specialist] Generating bridge: **{bridge_name}** ({producer_path} → {consumer_path})...", "stage": "executor"})

            # Step 1: Generate producer
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
                await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"  → Producer `{producer_path}` done.", "stage": "executor"})
            except Exception as e:
                await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"⚠️ [Specialist] Producer `{producer_path}` failed: {str(e)}", "stage": "executor"})

            # Step 2: Generate consumer using producer code as context
            consumer_sys = """You are a Frontend Specialist. Write ONLY this single consumer file.
The backend has already generated its code. Match its API contract perfectly.
Return ONLY valid JSON: {"path": "path/to/file", "content": "file content"}
DO NOT wrap in markdown."""
            consumer_user = f"{context}\n\nThe Backend generated this exact code for `{producer_path}`:\n\n```\n{produced_code}\n```\n\nWRITE THIS CONSUMER FILE to perfectly match it: {consumer_path}"

            try:
                raw, usage = await llm.generate(consumer_sys, consumer_user, model_name=model)
                record_executor_cost(model, usage)
                clean = raw.strip()
                if clean.startswith("```json"): clean = clean[7:]
                elif clean.startswith("```"): clean = clean[3:]
                if clean.endswith("```"): clean = clean[:-3]
                consumer_data = json.loads(clean.strip())
                result.append({"path": consumer_path, "content": consumer_data.get("content", "")})
                await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"  → Consumer `{consumer_path}` done. Bridge **{bridge_name}** complete.", "stage": "executor"})
            except Exception as e:
                await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"⚠️ [Specialist] Consumer `{consumer_path}` failed: {str(e)}", "stage": "executor"})

            return result

        # ---- Sub-Routine C: Swarm Worker (single isolated file) ----
        async def execute_swarm_worker(filepath: str, context: str, model: str) -> list:
            await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"⚡ [Swarm] Generating `{filepath}`...", "stage": "executor"})
            swarm_sys = """You are a Swarm Worker. Generate ONLY this single isolated file.
Return ONLY valid JSON: {"path": "path/to/file", "content": "file content"}
DO NOT wrap in markdown. NO explanations."""
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
            except Exception as e:
                await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"⚠️ [Swarm] `{filepath}` failed: {str(e)}", "stage": "executor"})
                return []

        # ---- Orchestrate with asyncio.gather ----
        wizard_model = models.get("executorWizard", models.get("executor", "anthropic/claude-3.5-sonnet"))
        specialist_model = models.get("executorSpecialist", models.get("executor", "google/gemini-2.5-flash"))
        swarm_model = models.get("executorSwarm", models.get("executor", "anthropic/claude-3-haiku"))

        # If no routing was produced (no topo graph), fall back to legacy single-wizard approach
        wizard_clusters = routing.get("wizard_clusters", [])
        specialist_pairs = routing.get("specialist_pairs", [])
        swarm_files = routing.get("swarm_files", [])

        if not wizard_clusters and not specialist_pairs and not swarm_files:
            # Full fallback: use legacy single-model executor
            await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "No routing data. Falling back to full-context single-model generation...", "stage": "executor"})
            legacy_model = models.get("executor", "anthropic/claude-3-haiku")
            legacy_sys = """You are the Senior Execution Drone.
Read the PRD and the Architect Plan, and translate them flawlessly into executable code.
CRITICAL MANDATE: NO CONVERSATIONAL FILLER. Do not explain your code. Do not say \"Here is the code.\"
Ensure all imports are present and the code is complete, not truncated."""
            legacy_user = f"""{shared_context}

=========================================
CRITICAL OUTPUT INSTRUCTIONS:
Return ONLY a valid JSON object: {{"files": [{{"path": "...", "content": "..."}}, ...]}}
DO NOT wrap in markdown.
========================================="""
            legacy_raw, usage = await llm.generate(legacy_sys, legacy_user, model_name=legacy_model)
            update_run_costs("3_executor", legacy_model, usage)
            clean_legacy = legacy_raw.strip()
            if clean_legacy.startswith("```json"): clean_legacy = clean_legacy[7:]
            elif clean_legacy.startswith("```"): clean_legacy = clean_legacy[3:]
            if clean_legacy.endswith("```"): clean_legacy = clean_legacy[:-3]
            try:
                legacy_data = json.loads(clean_legacy.strip())
                all_generated = legacy_data.get("files", [])
            except:
                all_generated = []
        else:
            tasks = []
            for cluster in wizard_clusters:
                tasks.append(execute_wizard(cluster, shared_context, wizard_model))
            for pair in specialist_pairs:
                tasks.append(execute_specialist(pair, shared_context, specialist_model))
            for filepath in swarm_files:
                tasks.append(execute_swarm_worker(filepath, shared_context, swarm_model))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Flatten results
            all_generated = []
            for res in results:
                if isinstance(res, list):
                    all_generated.extend(res)
                elif isinstance(res, Exception):
                    print(f"[Executor] Task error: {res}")

        # Write all files
        saved_files = []
        for file_obj in all_generated:
            path = file_obj.get("path", "").strip()
            content = file_obj.get("content", "")
            if path:
                safe_path = path.lstrip("/")
                full_path = f"{artifact_dir}/{safe_path}"
                fs_manager.write_file(full_path, content)
                saved_files.append(full_path)

        # Save executor raw artifact
        fs_manager.write_file(f"{artifact_dir}/3_executor_raw.json", json.dumps(all_generated, indent=2))

        summary_text = f"✅ **Parallel Execution Complete!**\n\nGenerated {len(saved_files)} file(s) across all task forces:\n" + "\n".join([f"- `{sf}`" for sf in saved_files])
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": summary_text, "stage": "executor"})
        files_list = fs_manager.list_files()
        await safe_send(websocket,{"event": "file_list", "files": files_list, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})

        # === Station 4.5: QA REVIEWER ===
        await safe_send(websocket,{"event": "station_update", "station": "qaReviewer", "status": "active"})
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "Reviewing codebase for architectural alignment...", "stage": "qaReviewer"})
        
        qa_model = models.get("qaReviewer", "google/gemini-2.5-flash")
        qa_sys_prompt = """You are the Lead QA Engineer. 
Review the architectural plan and the generated codebase below. 
Compare the codebase against the plan and PRD to ensure all requirements, UI elements, and logic were implemented correctly without hallucination.
Write a concise Markdown review document. Point out anything missing or incorrect, and explicitly state what looks good. Focus on major architectural misses or UI discrepancies."""
        
        codebase_context = ""
        for sf in saved_files:
            try:
                content = fs_manager.read_file(sf)
                codebase_context += f"\n--- {sf} ---\n{content}\n"
            except: pass
            
        qa_user_prompt = f"PLAN:\n{plan}\n\nGENERATED CODEBASE:\n{codebase_context}"
        
        qa_output, qa_usage = await llm.generate(qa_sys_prompt, qa_user_prompt, model_name=qa_model)
        
        fs_manager.write_file(f"{artifact_dir}/4_qa_review.md", qa_output)
        update_run_costs("4_qaReviewer", qa_model, qa_usage)
        files_list = fs_manager.list_files()
        await safe_send(websocket,{"event": "file_list", "files": files_list, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
        await safe_send(websocket,{
            "event": "chat", "sender": "swarm", "text": qa_output, "stage": "qaReviewer",
            "usage": {"prompt_tokens": qa_usage.prompt_tokens, "completion_tokens": qa_usage.completion_tokens, "model": qa_model}
        })
        await safe_send(websocket,{"event": "station_update", "station": "qaReviewer", "status": "complete"})
        
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": "Determining execution commands...", "stage": "executor"})
        runner_sys_prompt = """You are the DevOps Runner.
Read the architectural plan and generated files. Output the exact bash commands to install dependencies (e.g. pip3 install) and run the main application.
Output EXACTLY a valid JSON object. DO NOT wrap the JSON in markdown code blocks.
Schema:
{
  "commands": [
    "pip3 install pygame",
    "python3 snake_game.py"
  ]
}"""
        runner_user_prompt = f"PLAN:\n{plan}\n\nGENERATED FILES:\n{saved_files}"
        
        runner_output, _ = await llm.generate(runner_sys_prompt, runner_user_prompt, model_name=models.get("executor", "anthropic/claude-3-haiku"), is_json=True)
        
        # Parse JSON
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
            
    except Exception as e:
        await safe_send(websocket,{"event": "chat", "sender": "swarm", "text": f"Executor Error: {str(e)}", "stage": "executor"})

    await safe_send(websocket,{"event": "station_update", "station": "executor", "status": "complete"})
    await safe_send(websocket,{"event": "workflow_complete"})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_ws_connections.add(websocket)
    
    # Reload saved global workspace state
    state = load_ide_state()
    saved_workspace = state.get("last_workspace")
    if saved_workspace and os.path.isdir(saved_workspace):
        fs_manager.workspace_path = saved_workspace

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

            elif command == "swarm_message":
                msg = data.get("message", "Build something")
                models_dict = data.get("models", {})
                asyncio.create_task(execute_live_swarm(websocket, msg, models_dict))

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

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=6500, reload=False)
