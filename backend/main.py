import asyncio
import os
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()

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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    # Send initial file list
    files = fs_manager.list_files()
    await websocket.send_json({"type": "file_list", "files": files})
    try:
        while True:
            data = await websocket.receive_json()
            command = data.get("command")
            
            if command == "list_files":
                files = fs_manager.list_files(data.get("path", ""))
                await websocket.send_json({"type": "file_list", "files": files})
                
            elif command == "read_file":
                try:
                    content = fs_manager.read_file(data.get("path"))
                    await websocket.send_json({"type": "file_content", "path": data.get("path"), "content": content})
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": str(e)})
                    
            elif command == "write_file":
                try:
                    fs_manager.write_file(data.get("path"), data.get("content"))
                    await websocket.send_json({"type": "file_written", "path": data.get("path")})
                    files = fs_manager.list_files()
                    await websocket.send_json({"type": "file_list", "files": files})
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": str(e)})

            elif command == "swarm_message":
                msg = data.get("message")
                
                # Wait 2 sec
                await asyncio.sleep(2)
                
                mock_filename = "simulation.txt"
                
                # Stream back mock status response
                await websocket.send_json({
                    "type": "chat", 
                    "sender": "swarm", 
                    "text": f"Agent is editing {mock_filename}..."
                })
                
                # Push mock text update
                mock_content = f"Simulated code generation for prompt:\n'{msg}'\n\n```python\nprint('Hello World')\n```"
                fs_manager.write_file(mock_filename, mock_content)
                
                # UI mock code update
                await websocket.send_json({
                    "type": "monaco_update",
                    "path": mock_filename,
                    "content": mock_content
                })
                # Refresh file tree
                files = fs_manager.list_files()
                await websocket.send_json({"type": "file_list", "files": files})
                
    except WebSocketDisconnect:
        print("Client disconnected")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
