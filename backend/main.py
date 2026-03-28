import asyncio
import os
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(".env.local")

app = FastAPI()

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

class FileSystemManager:
    def __init__(self, workspace_path: str):
        self.workspace_path = os.path.abspath(workspace_path)
        os.makedirs(self.workspace_path, exist_ok=True)

    def _get_safe_path(self, relative_path: str) -> str:
        # Prevent trailing path traversal
        normalized = os.path.normpath(relative_path).lstrip("/")
        safe_path = os.path.abspath(os.path.join(self.workspace_path, normalized))
        if not safe_path.startswith(self.workspace_path):
            raise ValueError("Access denied: Paths outside the workspace are not allowed.")
        return safe_path

    def list_files(self, relative_path: str = ""):
        safe_path = self._get_safe_path(relative_path)
        if not os.path.exists(safe_path) or not os.path.isdir(safe_path):
            return []
        
        tree = []
        for item in os.listdir(safe_path):
            item_path = os.path.join(safe_path, item)
            is_dir = os.path.isdir(item_path)
            if item.startswith('.'):
                continue
            tree.append({
                "name": item,
                "path": os.path.relpath(item_path, self.workspace_path),
                "is_dir": is_dir
            })
        return tree

    def read_file(self, relative_path: str) -> str:
        safe_path = self._get_safe_path(relative_path)
        with open(safe_path, "r", encoding="utf-8") as f:
            return f.read()

    def write_file(self, relative_path: str, content: str):
        safe_path = self._get_safe_path(relative_path)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)

WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../workspace_sandbox"))
fs_manager = FileSystemManager(WORKSPACE_DIR)

llm = LLMEngine(os.getenv("OPENROUTER_API_KEY", ""))

async def execute_live_swarm(websocket: WebSocket, prompt: str, models: dict):
    # Let the UI reset state
    await websocket.send_json({"event": "workflow_start", "message": prompt})
    
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
                
            # Ensure directories exist
            dir_path = os.path.dirname(os.path.join(fs_manager.workspace_path, path))
            os.makedirs(dir_path, exist_ok=True)
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
    
    # Reload saved global workspace state
    state = load_ide_state()
    saved_workspace = state.get("last_workspace")
    if saved_workspace and os.path.isdir(saved_workspace):
        fs_manager.workspace_path = saved_workspace

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

            elif command == "save_config":
                try:
                    import json
                    config_data = data.get("config", {})
                    fs_manager.write_file("swarm_config.json", json.dumps(config_data, indent=2))
                    files = fs_manager.list_files()
                    await websocket.send_json({"event": "file_list", "files": files, "workspace_name": os.path.basename(fs_manager.workspace_path) or "Workspace"})
                except Exception as e:
                    await websocket.send_json({"event": "error", "message": f"Failed to save config: {str(e)}"})

            elif command == "swarm_message":
                msg = data.get("message", "Build something")
                models_dict = data.get("models", {})
                # Spawn simulate async task so websocket is not fully blocked if reading events
                asyncio.create_task(execute_live_swarm(websocket, msg, models_dict))
                
    except WebSocketDisconnect:
        print("Client disconnected")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=False)
