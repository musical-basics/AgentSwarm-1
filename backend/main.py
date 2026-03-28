import asyncio
import os
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(".env.local")

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

    async def generate(self, system_prompt: str, user_prompt: str, model_name: str = "google/gemini-2.5-flash") -> tuple[str, any]:
        response = await self.client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": "http://localhost:3008",
                "X-Title": "Flowmind IDE",
            },
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=4000,
        )
        return response.choices[0].message.content, response.usage

import json

STATE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".ide_state.json"))

def load_ide_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_ide_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

active_ws_connections = set()

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
                    await ws.send_json({"event": "file_list", "files": files, "workspace_name": workspace_name})
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

async def execute_agent_chat(websocket: WebSocket, message: str, model: str, history: list, fs_mgr: FileSystemManager):
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
    await websocket.send_json({"event": "agent_chat_typing", "model": model})

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
        await websocket.send_json({
            "event": "agent_chat_response",
            "text": f"⚠️ API Error: {str(e)}",
            "commands": [],
            "model": model,
        })
        return

    # Parse <cmd>...</cmd> blocks and execute them
    cmd_pattern = re.compile(r'<cmd>(.*?)</cmd>', re.DOTALL)
    commands_found = cmd_pattern.findall(text)
    command_results = []

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
        await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(workspace)})

    await websocket.send_json({
        "event": "agent_chat_response",
        "text": text,
        "commands": command_results,
        "model": model,
        "usage": {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens} if usage else {},
    })

async def execute_live_swarm(websocket: WebSocket, prompt: str, models: dict):

    # Let the UI reset state
    await websocket.send_json({"event": "workflow_start", "message": prompt})
    
    # Create artifacts directory
    os.makedirs(os.path.join(fs_manager.workspace_path, "_swarm_artifacts"), exist_ok=True)
    
    # === Station 1: The Origin ===
    print("Starting station: origin")
    await websocket.send_json({
        "event": "station_update", 
        "station": "origin", 
        "status": "active"
    })
    
    # Broadcast the raw idea to chat
    await websocket.send_json({
        "event": "chat",
        "sender": "swarm",
        "text": f"Raw Idea Captured: {prompt}",
        "stage": "origin"
    })
    
    # Save Origin artifact
    fs_manager.write_file("_swarm_artifacts/0_origin.md", prompt)
    files = fs_manager.list_files()
    await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
    
    # Complete origin
    await asyncio.sleep(0.5)
    await websocket.send_json({"event": "station_update", "station": "origin", "status": "complete"})
    
    # === Station 2: Spec Factory ===
    print("Starting station: specFactory")
    await websocket.send_json({
        "event": "station_update", 
        "station": "specFactory", 
        "status": "active"
    })
    
    # Send intermediate chat
    await websocket.send_json({
        "event": "chat",
        "sender": "swarm",
        "text": "Generating specifications via OpenRouter...",
        "stage": "specFactory"
    })
    
    try:
        # === Call OpenRouter API for Spec ===
        active_model = models.get("specFactory", "google/gemini-2.5-flash")
        sys_prompt = """You are the Product Manager (Spec Factory). 
Generate a comprehensive Product Requirements Document (PRD). You must define:
1. Core purpose of the project.
2. All required dependencies and libraries.
3. Explicitly define the exact file structure required."""
        
        spec, usage = await llm.generate(sys_prompt, f"ORIGINAL REQUEST:\n{prompt}", model_name=active_model)
        
        # Save Spec artifact
        fs_manager.write_file("_swarm_artifacts/1_spec.md", spec)
        files = fs_manager.list_files()
        await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
        
        # Broadcast the generated spec
        await websocket.send_json({
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
        await websocket.send_json({
            "event": "chat",
            "sender": "swarm",
            "text": f"LLM Error: {str(e)}",
            "stage": "specFactory"
        })
        spec = f"Fallback Spec for: {prompt}"
    
    # Complete specFactory
    await websocket.send_json({"event": "station_update", "station": "specFactory", "status": "complete"})
    
    # === Station 3: PLANNER ===
    print("Starting station: planner")
    await websocket.send_json({"event": "station_update", "station": "planner", "status": "active"})
    await websocket.send_json({"event": "chat", "sender": "swarm", "text": "Planning architecture and layout...", "stage": "planner"})
    try:
        active_model = models.get("planner", "google/gemini-2.5-flash")
        sys_prompt = """You are a Senior Systems Architect (Planner). 
Take the Spec and write out the exact, function-by-function pseudo-code and data flow for every single file.
Define exactly how the files import and interact with each other."""
        
        # Accumulate payload
        user_prompt = f"ORIGINAL REQUEST:\n{prompt}\n\nSPEC (PRD):\n{spec}"
        
        plan, usage = await llm.generate(sys_prompt, user_prompt, model_name=active_model)
        
        # Save Planner artifact
        fs_manager.write_file("_swarm_artifacts/2_plan.md", plan)
        files = fs_manager.list_files()
        await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
        
        await websocket.send_json({
            "event": "chat", "sender": "swarm", "text": plan, "stage": "planner", 
            "usage": {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens, "model": active_model}
        })
    except Exception as e:
        await websocket.send_json({"event": "chat", "sender": "swarm", "text": f"Planner Error: {str(e)}", "stage": "planner"})
        plan = "Fallback Plan: Proceed to execution."
    await websocket.send_json({"event": "station_update", "station": "planner", "status": "complete"})

    # === Station 4: EXECUTOR ===
    print("Starting station: executor")
    await websocket.send_json({"event": "station_update", "station": "executor", "status": "active"})
    await websocket.send_json({"event": "chat", "sender": "swarm", "text": "Writing code natively...", "stage": "executor"})
    try:
        # Flatten workspace list to inject environment context
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

        active_model = models.get("executor", "anthropic/claude-3-haiku")
        sys_prompt = """You are a junior syntax translator (Executor).
Read the exhaustive Plan and translate it directly into code.
IMPORTANT: Output each file exactly in this format so the system can extract it:
<file path="filename.ext">
...code...
</file>
Do not use markdown code blocks inside the <file> tag, just raw code."""
        
        # Accumulating Payload + Context Injection
        user_prompt = f"CURRENT WORKSPACE FILES:\n{existing_files_str}\n\nORIGINAL REQUEST:\n{prompt}\n\nSPEC (PRD):\n{spec}\n\nARCHITECT PLAN:\n{plan}"
        
        code_output, usage = await llm.generate(sys_prompt, user_prompt, model_name=active_model)
        
        # Save Executor Raw artifact
        fs_manager.write_file("_swarm_artifacts/3_executor_raw.md", code_output)
        
        # Robust Regex Extraction: Remove markdown blocks that wrap the <file> tags
        import re
        clean_output = code_output
        clean_output = re.sub(r'```[a-zA-Z]*\n(<file)', r'\1', clean_output)
        clean_output = re.sub(r'(</file>)\n```', r'\1', clean_output)
        
        file_matches = list(re.finditer(r'<file\s+path=["\']([^"\']+)["\']>\n?(.*?)\n?</file>', clean_output, re.DOTALL))
        saved_files = []
        for match in file_matches:
            path = match.group(1).strip()
            content = match.group(2)
            
            # Additional safety: gracefully strip markdown ticks inside the content if the LLM mistakenly injects them
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r'^```[a-zA-Z]*\n', '', content)
                content = re.sub(r'\n```$', '', content)
                
            # Use fs_manager strictly for boundary-safe recursive writing
            fs_manager.write_file(path, content)
            saved_files.append(path)
            
        text_out = f"Generated files physically successfully into workspace:\n" + "\n".join([f"- {sf}" for sf in saved_files]) if saved_files else "No files matched `<file path='...'>` format. Raw output included."
        if not saved_files:
            text_out += f"\n\n{code_output[:1000]}..."
            
        await websocket.send_json({
            "event": "chat", "sender": "swarm", "text": text_out, "stage": "executor", 
            "usage": {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens, "model": active_model}
        })
        files = fs_manager.list_files()
        await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
    except Exception as e:
        await websocket.send_json({"event": "chat", "sender": "swarm", "text": f"Executor Error: {str(e)}", "stage": "executor"})

    await websocket.send_json({"event": "station_update", "station": "executor", "status": "complete"})
    await websocket.send_json({"event": "workflow_complete"})

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
        await websocket.send_json({"event": "layout_loaded", "layout": state["layout"]})

    # Send initial file list
    files = fs_manager.list_files()
    await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
    
    # Try to load workspace-specific config automatically
    config_path = os.path.join(fs_manager.workspace_path, "swarm_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)
            await websocket.send_json({"event": "config_loaded", "config": config_data})
        except:
            pass
    
    try:
        while True:
            data = await websocket.receive_json()
            command = data.get("command")
            
            if command == "list_files":
                files = fs_manager.list_files(data.get("path", ""))
                await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
                
            elif command == "read_file":
                try:
                    content = fs_manager.read_file(data.get("path"))
                    await websocket.send_json({"event": "file_content", "path": data.get("path"), "content": content})
                except Exception as e:
                    await websocket.send_json({"event": "error", "message": str(e)})
                    
            elif command == "write_file":
                try:
                    fs_manager.write_file(data.get("path"), data.get("content"))
                    await websocket.send_json({"event": "file_written", "path": data.get("path")})
                    files = fs_manager.list_files()
                    await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
                except Exception as e:
                    await websocket.send_json({"event": "error", "message": str(e)})

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
                    
                    await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
                    
                    # Re-load config from new workspace
                    config_path = os.path.join(fs_manager.workspace_path, "swarm_config.json")
                    if os.path.exists(config_path):
                        try:
                            with open(config_path, "r") as f:
                                config_data = json.load(f)
                            await websocket.send_json({"event": "config_loaded", "config": config_data})
                        except:
                            pass
                else:
                    await websocket.send_json({"event": "error", "message": "Invalid directory path"})

            elif command == "save_layout":
                state["layout"] = data.get("layout", {})
                save_ide_state(state)

            elif command == "save_config":
                try:
                    import json
                    config_data = data.get("config", {})
                    fs_manager.write_file("swarm_config.json", json.dumps(config_data, indent=2))
                    files = fs_manager.list_files()
                    await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
                except Exception as e:
                    await websocket.send_json({"event": "error", "message": f"Failed to save config: {str(e)}"})

            elif command == "load_config":
                try:
                    import json
                    config_path = os.path.join(fs_manager.workspace_path, "swarm_config.json")
                    if os.path.exists(config_path):
                        with open(config_path, "r") as f:
                            config_data = json.load(f)
                        await websocket.send_json({"event": "config_loaded", "config": config_data})
                        await websocket.send_json({"event": "chat", "sender": "swarm", "text": "Configuration loaded from workspace.", "stage": "origin"})
                    else:
                        await websocket.send_json({"event": "error", "message": "No swarm_config.json found in the current workspace."})
                except Exception as e:
                    await websocket.send_json({"event": "error", "message": f"Failed to load config: {str(e)}"})

            elif command == "swarm_message":
                msg = data.get("message", "Build something")
                models_dict = data.get("models", {})
                asyncio.create_task(execute_live_swarm(websocket, msg, models_dict))

            elif command == "chat_message":
                msg = data.get("message", "")
                model = data.get("model", "google/gemini-2.5-flash")
                history = data.get("history", [])
                asyncio.create_task(execute_agent_chat(websocket, msg, model, history, fs_manager))

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
                    await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path)})
                except Exception as e:
                    await websocket.send_json({"event": "error", "message": f"Rename failed: {str(e)}"})

            elif command == "delete_file":
                try:
                    import shutil
                    target_path = fs_manager._get_safe_path(data.get("path", ""))
                    if os.path.isdir(target_path):
                        shutil.rmtree(target_path)
                    else:
                        os.remove(target_path)
                    files = fs_manager.list_files()
                    await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path)})
                except Exception as e:
                    await websocket.send_json({"event": "error", "message": f"Delete failed: {str(e)}"})

            elif command == "reveal_in_finder":
                try:
                    target_path = fs_manager._get_safe_path(data.get("path", ""))
                    # Use the directory if it's a file
                    reveal_path = target_path if os.path.isdir(target_path) else os.path.dirname(target_path)
                    import subprocess
                    subprocess.Popen(["open", "-R", target_path])
                except Exception as e:
                    await websocket.send_json({"event": "error", "message": f"Reveal failed: {str(e)}"})

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
            # CRITICAL: Prevent Zombie Processes
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                os.close(fd)
            except Exception as e:
                print(f"Cleanup error for PTY {pid}: {e}")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=6500, reload=False)
