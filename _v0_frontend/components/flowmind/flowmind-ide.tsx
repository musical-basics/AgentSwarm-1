"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useMonaco } from "@monaco-editor/react";
import { PanelGroup, Panel, PanelResizeHandle } from "react-resizable-panels";
import { TerminalPanel } from "./terminal-panel";
import {
  Sparkles,
  Shield,
  Users,
  FileCode,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  Send,
  Zap,
  Command,
  Play,
  Terminal,
  Settings,
  Search,
  GitBranch,
  GripVertical,
  GripHorizontal,
  Save,
  Download,
} from "lucide-react";

type NodeStatus = "idle" | "active" | "complete";

interface NodeState {
  origin: NodeStatus;
  specFactory: NodeStatus;
  planner: NodeStatus;
  executor: NodeStatus;
}

interface ConnectionState {
  originToSpec: boolean;
  specToPlanner: boolean;
  plannerToExecutor: boolean;
}

interface FileItem {
  name: string;
  type: "file" | "folder";
  children?: FileItem[];
  expanded?: boolean;
}

interface ChatMessage {
  role: "user" | "agent";
  content: string;
  stage?: string;
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    model: string;
  };
}

const initialFiles: FileItem[] = [
  {
    name: "src",
    type: "folder",
    expanded: true,
    children: [
      { name: "hello_swarm.py", type: "file" },
      { name: "config.py", type: "file" },
      { name: "utils.py", type: "file" },
    ],
  },
  {
    name: "tests",
    type: "folder",
    children: [{ name: "test_swarm.py", type: "file" }],
  },
  { name: "README.md", type: "file" },
  { name: "requirements.txt", type: "file" },
];

const fileContents: Record<string, string> = {
  "hello_swarm.py": `print("Hello Swarm! This is a test file.")

def greet_agent(name: str) -> str:
    """Greet an agent by name."""
    return f"Welcome, {name}!"

if __name__ == "__main__":
    print(greet_agent("Flowmind"))`,
  "config.py": `# Flowmind Configuration
SWARM_SIZE = 4
MAX_ITERATIONS = 100
DEBUG_MODE = True`,
  "utils.py": `def format_output(text: str) -> str:
    return f"[SWARM] {text}"`,
  "test_swarm.py": `import pytest
from src.hello_swarm import greet_agent

def test_greet_agent():
    assert greet_agent("Test") == "Welcome, Test!"`,
  "README.md": `# Flowmind Swarm Project
A demonstration of AI agent swarm coordination.`,
  "requirements.txt": `pytest>=7.0.0
numpy>=1.24.0
rich>=13.0.0`,
};

declare global {
  interface Window {
    electronAPI?: {
      openDirectory: () => Promise<string | null>;
    };
  }
}

import Editor from "@monaco-editor/react";

export function FlowmindIDE() {

  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [fileContentsCache, setFileContentsCache] = useState<Record<string, string>>({});
  const [nodeState, setNodeState] = useState<NodeState>({
    origin: "idle",
    specFactory: "idle",
    planner: "idle",
    executor: "idle",
  });

  const monaco = useMonaco();

  useEffect(() => {
    if (monaco) {
      monaco.editor.defineTheme('cyberpunk', {
        base: 'vs-dark',
        inherit: true,
        rules: [
          { token: 'string', foreground: 'fbbf24' },
          { token: 'comment', foreground: '34d39999', fontStyle: 'italic' },
          { token: 'keyword', foreground: 'a855f7' },
          { token: 'identifier', foreground: 'cccccc' },
          { token: 'type.identifier', foreground: '34d399' },
          { token: 'function', foreground: '22d3ee' },
        ],
        colors: {
          'editor.background': '#0a0a0f',
          'editor.foreground': '#cccccc',
          'editor.lineHighlightBackground': '#22d3ee0d',
          'editorLineNumber.foreground': '#22d3ee4d',
          'editorLineNumber.activeForeground': '#22d3ee99',
          'editorIndentGuide.background': '#22d3ee1a',
        }
      });
      monaco.editor.setTheme('cyberpunk');
    }
  }, [monaco]);

  const [connectionState, setConnectionState] = useState<ConnectionState>({
    originToSpec: false,
    specToPlanner: false,
    plannerToExecutor: false,
  });

  const [isSimulating, setIsSimulating] = useState(false);
  const [files, setFiles] = useState<FileItem[]>(initialFiles);
  const [selectedFile, setSelectedFile] = useState("hello_swarm.py");
  
  // Context menu state
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; path: string; isDir: boolean } | null>(null);
  const [renamingPath, setRenamingPath] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    { role: "agent", content: "Send a prompt to test the Flowmind simulator." },
  ]);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const [modelOptions, setModelOptions] = useState<any[]>([]);
  const [nodeModels, setNodeModels] = useState({
    origin: "google/gemini-2.5-flash",
    specFactory: "anthropic/claude-3-haiku",
    planner: "google/gemini-2.5-flash",
    executor: "anthropic/claude-3-haiku",
  });

  const handleExportModels = () => {
    if (!modelOptions.length) return;
    const headers = ["ID", "Name", "Context Length", "Prompt Cost ($)", "Completion Cost ($)", "Image Cost ($)", "Architecture/Modality"];
    const escape = (str: any) => `"${String(str || "").replace(/"/g, '""')}"`;
    const rows = modelOptions.map(m => {
      const p = m.pricing || {};
      const arch = m.architecture ? `${m.architecture.modality || "text"} (${m.architecture.instruct_type || "base"})` : "Text (General)";
      return [escape(m.id), escape(m.name), escape(m.context_length), escape(p.prompt), escape(p.completion), escape(p.image), escape(arch)].join(",");
    });
    const blob = new Blob([headers.join(",") + "\n" + rows.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", "openrouter_models.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  useEffect(() => {
    fetch("https://openrouter.ai/api/v1/models")
      .then(res => res.json())
      .then(data => {
        if (data && data.data) {
          const sorted = data.data.sort((a: any, b: any) => a.name.localeCompare(b.name));
          setModelOptions(sorted);
        }
      })
      .catch(console.error);
  }, []);

  // Resizable panel state
  const [sidebarWidth, setSidebarWidth] = useState(256);
  const [rightPanelWidth, setRightPanelWidth] = useState(480);
  const [chatHeight, setChatHeight] = useState(280);
  const containerRef = useRef<HTMLDivElement>(null);

  // Drag state
  const [isDragging, setIsDragging] = useState<"sidebar" | "rightPanel" | "chat" | null>(null);
  const dragStartRef = useRef({ x: 0, y: 0, value: 0 });

  useEffect(() => {
    let ws: WebSocket;
    const connect = () => {
      ws = new WebSocket("ws://127.0.0.1:8765/ws");
      ws.onopen = () => {
        console.log("Connected to backend");
        setSocket(ws);
        ws.send(JSON.stringify({ command: "list_files", path: "" }));
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.event === "file_list") {
          setFiles(prev => {
            const getExpandedFolders = (items: FileItem[], paths: Set<string>, currentPath: string = "") => {
              for (const item of items) {
                const itemPath = currentPath ? `${currentPath}/${item.name}` : item.name;
                if (item.expanded) paths.add(itemPath);
                if (item.children) getExpandedFolders(item.children, paths, itemPath);
              }
              return paths;
            };
            const expandedSet = getExpandedFolders(prev, new Set());

            const processFiles = (list: any[], currentPath: string = ""): FileItem[] => {
              return list.map((f: any) => {
                const itemPath = currentPath ? `${currentPath}/${f.name}` : f.name;
                return {
                  name: f.name,
                  type: f.is_dir ? "folder" as any : "file" as any,
                  children: f.children ? processFiles(f.children, itemPath) : [], 
                  expanded: expandedSet.has(itemPath) || f.name === "_swarm_artifacts"
                };
              });
            };
            
            const workspaceName = data.workspace_name || "Active Workspace";
            const rootExpanded = prev.length > 0 ? prev[0].expanded : true;
            
            return [{
              name: workspaceName,
              type: "folder" as any,
              expanded: rootExpanded,
              children: processFiles(data.files || [], workspaceName)
            }];
          });
        } else if (data.event === "config_loaded") {
          if (data.config) {
             setNodeModels(prev => ({ ...prev, ...data.config }));
          }
        } else if (data.event === "file_content") {
          setFileContentsCache(prev => ({ ...prev, [data.path]: data.content }));
          setSelectedFile(data.path);
        } else if (data.event === "chat") {
          setChatMessages(prev => [...prev, { role: data.sender === "swarm" ? "agent" as any : "user" as any, content: data.text, stage: data.stage, usage: data.usage }]);
        } else if (data.event === "monaco_update") {
          setFileContentsCache(prev => ({ ...prev, [data.path]: data.content }));
          setSelectedFile(data.path);
        } else if (data.event === "station_update") {
          setNodeState(prev => ({ ...prev, [data.station]: data.status }));
          
          if (data.station === "origin" && data.status === "complete") {
             setConnectionState(prev => ({ ...prev, originToSpec: true }));
          } else if (data.station === "specFactory" && data.status === "complete") {
             setConnectionState(prev => ({...prev, originToSpec: false, specToPlanner: true }));
          } else if (data.station === "planner" && data.status === "complete") {
             setConnectionState(prev => ({ ...prev, specToPlanner: false, plannerToExecutor: true }));
          } else if (data.station === "executor" && data.status === "complete") {
             setConnectionState(prev => ({ ...prev, plannerToExecutor: false }));
          }
        } else if (data.event === "workflow_start") {
          setIsSimulating(true);
          setNodeState({ origin: "idle", specFactory: "idle", planner: "idle", executor: "idle" });
          setConnectionState({ originToSpec: false, specToPlanner: false, plannerToExecutor: false });
        } else if (data.event === "workflow_complete") {
          setIsSimulating(false);
          setChatMessages(prev => [...prev, { role: "agent" as any, content: "Swarm workflow complete! Ready for next task." }]);
        }
      };

      ws.onclose = () => {
        setTimeout(connect, 3000);
      };
    };
    connect();
    return () => ws?.close();
  }, []);

  const handleOpenFolder = async () => {
    console.log("[OpenFolder] Button clicked");
    console.log("[OpenFolder] window.electronAPI:", window.electronAPI);
    console.log("[OpenFolder] socket state:", socket?.readyState);
    
    if (window.electronAPI) {
      console.log("[OpenFolder] Calling electronAPI.openDirectory()...");
      const folderPath = await window.electronAPI.openDirectory();
      console.log("[OpenFolder] Got folder path:", folderPath);
      
      if (folderPath && socket) {
        console.log("[OpenFolder] Sending set_workspace to backend:", folderPath);
        socket.send(JSON.stringify({ command: "set_workspace", path: folderPath }));
      } else {
        console.warn("[OpenFolder] Aborted - folderPath:", folderPath, "socket:", socket?.readyState);
      }
    } else {
      console.warn("[OpenFolder] window.electronAPI is undefined - not running in Electron?");
      alert("Please run inside electron to open folders.");
    }
  };


  const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  // Handle resize dragging
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging) return;

      if (isDragging === "sidebar") {
        const delta = e.clientX - dragStartRef.current.x;
        const newWidth = Math.max(180, Math.min(400, dragStartRef.current.value + delta));
        setSidebarWidth(newWidth);
      } else if (isDragging === "rightPanel") {
        const delta = dragStartRef.current.x - e.clientX;
        const newWidth = Math.max(300, Math.min(700, dragStartRef.current.value + delta));
        setRightPanelWidth(newWidth);
      } else if (isDragging === "chat") {
        const delta = dragStartRef.current.y - e.clientY;
        const newHeight = Math.max(150, Math.min(500, dragStartRef.current.value + delta));
        setChatHeight(newHeight);
      }
    };

    const handleMouseUp = () => {
      setIsDragging(null);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    if (isDragging) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = isDragging === "chat" ? "ns-resize" : "ew-resize";
      document.body.style.userSelect = "none";
    }

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging]);

  const startDragging = (type: "sidebar" | "rightPanel" | "chat", e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(type);
    dragStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      value: type === "sidebar" ? sidebarWidth : type === "rightPanel" ? rightPanelWidth : chatHeight,
    };
  };

  

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (chatInput.trim() && !isSimulating) {
      if (socket) socket.send(JSON.stringify({ command: "swarm_message", message: chatInput.trim(), models: nodeModels }));
      setChatInput("");
    }
  };

  const toggleFolder = (path: string[]) => {
    setFiles((prev) => {
      const newFiles = JSON.parse(JSON.stringify(prev));
      let current = newFiles;
      for (let i = 0; i < path.length - 1; i++) {
        current = current.find((f: FileItem) => f.name === path[i])?.children || [];
      }
      const folder = current.find((f: FileItem) => f.name === path[path.length - 1]);
      if (folder) {
        folder.expanded = !folder.expanded;
      }
      return newFiles;
    });
  };

  const handleContextMenuAction = (action: string, path: string) => {
    setContextMenu(null);
    if (!socket) return;
    if (action === "reveal") {
      socket.send(JSON.stringify({ command: "reveal_in_finder", path }));
    } else if (action === "delete") {
      if (confirm(`Delete "${path.split("/").pop()}"? This cannot be undone.`)) {
        socket.send(JSON.stringify({ command: "delete_file", path }));
      }
    } else if (action === "rename") {
      setRenamingPath(path);
      setRenameValue(path.split("/").pop() || "");
    }
  };

  const submitRename = () => {
    if (!socket || !renamingPath || !renameValue.trim()) return;
    socket.send(JSON.stringify({ command: "rename_file", old_path: renamingPath, new_name: renameValue.trim() }));
    setRenamingPath(null);
  };

  return (
    <div ref={containerRef} className="h-screen w-screen flex flex-col bg-[#0a0a0f] text-[#cccccc] font-mono text-sm overflow-hidden">
      {/* Animated Background Grid */}
      <div
        className="fixed inset-0 opacity-30 pointer-events-none"
        style={{
          backgroundImage: `radial-gradient(circle at 1px 1px, rgba(34,211,238,0.15) 1px, transparent 0)`,
          backgroundSize: "32px 32px",
        }}
      />

      {/* Window Chrome - Cyberpunk Style */}
      <div className="relative flex items-center h-10 bg-gradient-to-r from-[#0d0d12] via-[#151520] to-[#0d0d12] border-b border-[#22d3ee]/30 px-3 shrink-0">
        {/* Glowing edge */}
        <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-[#22d3ee]/50 to-transparent" />
        
        <div className="flex items-center gap-2">
          <motion.div 
            className="w-3 h-3 rounded-full bg-[#ff5f57]"
            style={{ boxShadow: "0 0 8px rgba(255,95,87,0.6), 0 0 16px rgba(255,95,87,0.3)" }}
            animate={{ boxShadow: ["0 0 8px rgba(255,95,87,0.6)", "0 0 12px rgba(255,95,87,0.8)", "0 0 8px rgba(255,95,87,0.6)"] }}
            transition={{ duration: 2, repeat: Infinity }}
          />
          <motion.div 
            className="w-3 h-3 rounded-full bg-[#febc2e]"
            style={{ boxShadow: "0 0 8px rgba(254,188,46,0.6), 0 0 16px rgba(254,188,46,0.3)" }}
            animate={{ boxShadow: ["0 0 8px rgba(254,188,46,0.6)", "0 0 12px rgba(254,188,46,0.8)", "0 0 8px rgba(254,188,46,0.6)"] }}
            transition={{ duration: 2, repeat: Infinity, delay: 0.3 }}
          />
          <motion.div 
            className="w-3 h-3 rounded-full bg-[#28c840]"
            style={{ boxShadow: "0 0 8px rgba(40,200,64,0.6), 0 0 16px rgba(40,200,64,0.3)" }}
            animate={{ boxShadow: ["0 0 8px rgba(40,200,64,0.6)", "0 0 12px rgba(40,200,64,0.8)", "0 0 8px rgba(40,200,64,0.6)"] }}
            transition={{ duration: 2, repeat: Infinity, delay: 0.6 }}
          />
        </div>
        <div className="flex-1 text-center text-xs text-[#22d3ee]/60 tracking-widest uppercase">frontend</div>
      </div>

      {/* Menu Bar - Cyberpunk Style */}
      <div className="relative flex items-center h-9 bg-gradient-to-r from-[#0d0d12] via-[#12121a] to-[#0d0d12] border-b border-[#a855f7]/20 px-4 gap-4 shrink-0">
        <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-[#a855f7]/30 to-transparent" />
        
        <div className="flex items-center gap-2">
          <motion.div
            animate={{ rotate: [0, 360] }}
            transition={{ duration: 8, repeat: Infinity, ease: "linear" }}
          >
            <Command className="w-4 h-4 text-[#22d3ee]" style={{ filter: "drop-shadow(0 0 4px rgba(34,211,238,0.5))" }} />
          </motion.div>
          <span className="text-xs font-bold tracking-wider bg-gradient-to-r from-[#22d3ee] via-[#a855f7] to-[#22d3ee] bg-clip-text text-transparent">
            FLOWMIND FACTORY IDE
          </span>
        </div>
        
        {/* Menu Items */}
        <div className="flex items-center gap-4 ml-auto">
          <button className="flex items-center gap-1.5 text-[10px] text-[#808080] hover:text-[#22d3ee] transition-colors uppercase tracking-wider">
            <Search className="w-3 h-3" />
            Search
          </button>
          <button className="flex items-center gap-1.5 text-[10px] text-[#808080] hover:text-[#a855f7] transition-colors uppercase tracking-wider">
            <GitBranch className="w-3 h-3" />
            main
          </button>
          <button className="flex items-center gap-1.5 text-[10px] text-[#808080] hover:text-[#34d399] transition-colors uppercase tracking-wider">
            <Settings className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex flex-1 min-h-0">
        {/* Left Sidebar - File Explorer with Cyberpunk Style */}
        <div 
          className="bg-gradient-to-b from-[#0d0d12] to-[#0a0a0f] border-r border-[#22d3ee]/20 flex flex-col shrink-0 relative"
          style={{ width: sidebarWidth }}
        >
          {/* Glowing edge */}
          <div className="absolute top-0 right-0 bottom-0 w-px bg-gradient-to-b from-[#22d3ee]/40 via-[#a855f7]/20 to-[#22d3ee]/40" />
          
          <div className="px-3 py-3 border-b border-[#22d3ee]/10 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Terminal className="w-3.5 h-3.5 text-[#22d3ee]" style={{ filter: "drop-shadow(0 0 4px rgba(34,211,238,0.5))" }} />
              <span className="text-[10px] font-semibold text-[#22d3ee] uppercase tracking-wider">
                Workspace Sandbox
              </span>
            </div>
            <button
              onClick={handleOpenFolder}
              className="p-1 hover:bg-[#22d3ee]/10 rounded transition-colors text-[#808080] hover:text-[#22d3ee]"
              title="Open Folder"
            >
              <FolderOpen className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="flex-1 overflow-auto px-1 py-2 relative" onClick={() => setContextMenu(null)}>
            <FileTree
              items={files}
              selectedFile={selectedFile}
              onSelectFile={(name) => { setSelectedFile(name); if (socket) socket.send(JSON.stringify({ command: "read_file", path: name })); }}
              onToggleFolder={toggleFolder}
              onContextMenu={(e: React.MouseEvent, path: string, isDir: boolean) => {
                e.preventDefault();
                setContextMenu({ x: e.clientX, y: e.clientY, path, isDir });
              }}
              renamingPath={renamingPath}
              renameValue={renameValue}
              setRenameValue={setRenameValue}
              onRenameSubmit={submitRename}
              onRenameCancel={() => setRenamingPath(null)}
              path={[]}
            />
          </div>
          
          {/* Context Menu */}
          {contextMenu && (
            <div
              className="fixed z-50 bg-[#12121a] border border-[#22d3ee]/30 rounded-lg overflow-hidden shadow-xl py-1 min-w-[160px]"
              style={{ left: contextMenu.x, top: contextMenu.y, boxShadow: "0 0 20px rgba(34,211,238,0.2)" }}
              onClick={(e) => e.stopPropagation()}
            >
              <button
                className="flex items-center gap-2 w-full px-3 py-2 text-xs text-[#cccccc] hover:bg-[#22d3ee]/10 hover:text-[#22d3ee] transition-colors"
                onClick={() => { handleContextMenuAction("rename", contextMenu.path); }}
              >
                <span className="text-[#22d3ee]">✏️</span> Rename
              </button>
              <button
                className="flex items-center gap-2 w-full px-3 py-2 text-xs text-[#cccccc] hover:bg-[#22d3ee]/10 hover:text-[#22d3ee] transition-colors"
                onClick={() => { handleContextMenuAction("reveal", contextMenu.path); }}
              >
                <span className="text-[#fbbf24]">📂</span> Reveal in Finder
              </button>
              <div className="border-t border-[#22d3ee]/10 my-1" />
              <button
                className="flex items-center gap-2 w-full px-3 py-2 text-xs text-[#ef4444] hover:bg-[#ef4444]/10 transition-colors"
                onClick={() => { handleContextMenuAction("delete", contextMenu.path); }}
              >
                <span>🗑️</span> Delete
              </button>
            </div>
          )}
        </div>

        {/* Sidebar Resize Handle */}
        <div
          className="w-1 shrink-0 cursor-ew-resize group relative hover:bg-[#22d3ee]/30 transition-colors"
          onMouseDown={(e) => startDragging("sidebar", e)}
        >
          <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-4 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
            <GripVertical className="w-3 h-3 text-[#22d3ee]/60" />
          </div>
          <motion.div 
            className="absolute inset-y-0 left-0 w-px"
            style={{ background: "linear-gradient(to bottom, transparent, #22d3ee, transparent)" }}
            animate={{ opacity: isDragging === "sidebar" ? 1 : 0 }}
          />
        </div>

        {/* Center - Code Editor with Cyberpunk Style */}
        <div className="flex-1 flex min-w-0 relative">
          <PanelGroup direction="vertical">
            <Panel defaultSize={70} minSize={30} className="flex flex-col min-h-0 relative">
              {/* Tab Bar */}
              <div className="h-10 bg-gradient-to-r from-[#0d0d12] to-[#12121a] border-b border-[#a855f7]/20 flex items-center shrink-0 relative">
                <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-[#a855f7]/30 via-[#22d3ee]/20 to-transparent" />
                
                <motion.div 
                  className="flex items-center h-full px-4 bg-[#0a0a0f] border-r border-[#22d3ee]/30 gap-2 relative"
                  whileHover={{ backgroundColor: "rgba(34,211,238,0.05)" }}
                >
                  <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#22d3ee]" style={{ boxShadow: "0 0 8px rgba(34,211,238,0.5)" }} />
                  <FileText className="w-3.5 h-3.5 text-[#22d3ee]" />
                  <span className="text-xs text-[#22d3ee]">{selectedFile}</span>
                </motion.div>
              </div>

              {/* Editor Content */}
              <div className="flex-1 overflow-auto bg-[#0a0a0f] relative min-h-0">
                {/* Subtle scanlines */}
                <div 
                  className="absolute inset-0 pointer-events-none opacity-5 z-10"
                  style={{
                    background: "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(34,211,238,0.03) 2px, rgba(34,211,238,0.03) 4px)",
                  }}
                />
                
                <Editor
                  height="100%"
                  theme="cyberpunk"
                  path={selectedFile}
                  value={fileContentsCache[selectedFile] || "// Loading..."}
                  options={{ 
                    readOnly: true, 
                    minimap: { enabled: false }, 
                    fontFamily: "Menlo, Monaco, 'Courier New', monospace",
                    fontSize: 13,
                    lineHeight: 24,
                    padding: { top: 16, bottom: 16 },
                    scrollbar: {
                      vertical: 'hidden',
                      horizontal: 'hidden'
                    },
                    overviewRulerLanes: 0,
                    hideCursorInOverviewRuler: true,
                    overviewRulerBorder: false,
                  }}
                />
              </div>
            </Panel>
            
            {/* Horizontal Resize handle between Editor and Terminal */}
            <PanelResizeHandle className="h-1 bg-[#22d3ee]/10 hover:bg-[#22d3ee]/40 transition-colors cursor-row-resize shrink-0">
              <div className="w-full h-full relative group">
                  <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-[2px] opacity-0 group-hover:opacity-100 transition-opacity bg-gradient-to-r from-transparent via-[#22d3ee] to-transparent shadow-[0_0_8px_rgba(34,211,238,0.8)]" />
              </div>
            </PanelResizeHandle>
            
            <Panel defaultSize={30} minSize={20} className="flex flex-col min-h-0 relative">
              <TerminalPanel />
            </Panel>
          </PanelGroup>
        </div>

        {/* Right Panel Resize Handle */}
        <div
          className="w-1 shrink-0 cursor-ew-resize group relative hover:bg-[#a855f7]/30 transition-colors"
          onMouseDown={(e) => startDragging("rightPanel", e)}
        >
          <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-4 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
            <GripVertical className="w-3 h-3 text-[#a855f7]/60" />
          </div>
          <motion.div 
            className="absolute inset-y-0 left-0 w-px"
            style={{ background: "linear-gradient(to bottom, transparent, #a855f7, transparent)" }}
            animate={{ opacity: isDragging === "rightPanel" ? 1 : 0 }}
          />
        </div>

        {/* Right Panel - Workflow + Chat with Cyberpunk Style */}
        <div 
          className="bg-[#0a0a0f] border-l border-[#a855f7]/30 flex flex-col shrink-0 relative"
          style={{ width: rightPanelWidth }}
        >
          {/* Glowing edge */}
          <div className="absolute top-0 left-0 bottom-0 w-px bg-gradient-to-b from-[#a855f7]/40 via-[#22d3ee]/20 to-[#34d399]/40" />
          
          {/* Workflow Visualization */}
          <div className="flex-1 relative overflow-hidden">
            {/* Animated Grid Background */}
            <div
              className="absolute inset-0 opacity-30"
              style={{
                backgroundImage: `radial-gradient(circle at 1px 1px, rgba(34,211,238,0.3) 1px, transparent 0)`,
                backgroundSize: "20px 20px",
              }}
            />

            {/* Ambient Glow Effects */}
            <motion.div
              className="absolute top-1/4 left-1/4 w-64 h-64 rounded-full blur-3xl"
              style={{ background: "radial-gradient(circle, rgba(34,211,238,0.15) 0%, transparent 70%)" }}
              animate={{ opacity: [0.4, 0.7, 0.4], scale: [1, 1.15, 1] }}
              transition={{ duration: 4, repeat: Infinity }}
            />
            <motion.div
              className="absolute bottom-1/4 right-1/4 w-64 h-64 rounded-full blur-3xl"
              style={{ background: "radial-gradient(circle, rgba(168,85,247,0.15) 0%, transparent 70%)" }}
              animate={{ opacity: [0.4, 0.7, 0.4], scale: [1, 1.15, 1] }}
              transition={{ duration: 4, repeat: Infinity, delay: 2 }}
            />
            <motion.div
              className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-48 h-48 rounded-full blur-3xl"
              style={{ background: "radial-gradient(circle, rgba(52,211,153,0.1) 0%, transparent 70%)" }}
              animate={{ opacity: [0.3, 0.5, 0.3], scale: [0.9, 1.1, 0.9] }}
              transition={{ duration: 5, repeat: Infinity, delay: 1 }}
            />

            {/* Workflow Graph */}
            <div className="relative z-10 flex flex-col items-center justify-center h-full p-6">
              {/* Top Action Buttons */}
              <div className="absolute top-4 right-4 flex items-center gap-3 z-30">
                <motion.button
                  onClick={handleExportModels}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider transition-all"
                  style={{
                    background: "rgba(168,85,247,0.1)",
                    border: "1px solid rgba(168,85,247,0.3)",
                    color: "#a855f7",
                  }}
                  whileHover={{ 
                    scale: 1.05,
                    backgroundColor: "rgba(168,85,247,0.2)",
                    boxShadow: "0 0 15px rgba(168,85,247,0.3)",
                  }}
                  whileTap={{ scale: 0.95 }}
                >
                  <Download className="w-3.5 h-3.5" />
                  Export Models
                </motion.button>

                <motion.button
                  onClick={() => {
                    if (socket) {
                      socket.send(JSON.stringify({ command: "load_config" }));
                    } else {
                      alert("Not connected to backend");
                    }
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider transition-all"
                  style={{
                    background: "rgba(34,211,238,0.1)",
                    border: "1px solid rgba(34,211,238,0.3)",
                    color: "#22d3ee",
                  }}
                  whileHover={{ 
                    scale: 1.05,
                    backgroundColor: "rgba(34,211,238,0.2)",
                    boxShadow: "0 0 15px rgba(34,211,238,0.3)",
                  }}
                  whileTap={{ scale: 0.95 }}
                >
                  <FolderOpen className="w-3.5 h-3.5" />
                  Open Config
                </motion.button>

                <motion.button
                  onClick={() => {
                    if (socket) {
                      socket.send(JSON.stringify({ command: "save_config", config: nodeModels }));
                      setChatMessages(prev => [...prev, { role: "agent", content: "Saved configuration to swarm_config.json" }]);
                    } else {
                      alert("Not connected to backend");
                    }
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider transition-all"
                  style={{
                    background: "rgba(34,211,238,0.1)",
                    border: "1px solid rgba(34,211,238,0.3)",
                    color: "#22d3ee",
                  }}
                  whileHover={{ 
                    scale: 1.05,
                    backgroundColor: "rgba(34,211,238,0.2)",
                    boxShadow: "0 0 15px rgba(34,211,238,0.3)",
                  }}
                  whileTap={{ scale: 0.95 }}
                >
                  <Save className="w-3.5 h-3.5" />
                  Save Config
                </motion.button>

                <motion.button
                  onClick={() => { if (chatInput.trim() && socket) socket.send(JSON.stringify({ command: "swarm_message", message: chatInput.trim(), models: nodeModels })); else alert("Type a message to simulate swarm"); }}
                  disabled={isSimulating}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{
                    background: isSimulating 
                      ? "linear-gradient(135deg, rgba(34,211,238,0.1) 0%, rgba(168,85,247,0.1) 100%)" 
                      : "linear-gradient(135deg, rgba(34,211,238,0.2) 0%, rgba(168,85,247,0.2) 100%)",
                    border: "1px solid rgba(34,211,238,0.5)",
                    boxShadow: isSimulating 
                      ? "none" 
                      : "0 0 20px rgba(34,211,238,0.3), inset 0 0 20px rgba(34,211,238,0.1)",
                    color: "#22d3ee",
                  }}
                  whileHover={!isSimulating ? { 
                    scale: 1.05,
                    boxShadow: "0 0 30px rgba(34,211,238,0.5), inset 0 0 30px rgba(34,211,238,0.2)",
                  } : {}}
                  whileTap={!isSimulating ? { scale: 0.95 } : {}}
                >
                  <Play className={`w-3.5 h-3.5 ${isSimulating ? "animate-spin" : ""}`} />
                  {isSimulating ? "Simulating..." : "Simulate Swarm"}
                </motion.button>
              </div>

              {/* Top Row: Origin and Spec */}
              <div className="flex items-center gap-4 mb-6 mt-12">
                <div className="relative">
                  <NodeModelSelector value={nodeModels.origin} onChange={v => setNodeModels(p => ({...p, origin: v}))} options={modelOptions} />
                  <WorkflowNode
                    title="THE ORIGIN"
                    status={nodeState.origin}
                    color="cyan"
                    icon={<SparkIcon status={nodeState.origin} />}
                  />
                </div>
                <ConnectionLine active={connectionState.originToSpec} />
                <div className="relative">
                  <NodeModelSelector value={nodeModels.specFactory} onChange={v => setNodeModels(p => ({...p, specFactory: v}))} options={modelOptions} />
                  <WorkflowNode
                    title="SPEC FACTORY"
                    status={nodeState.specFactory}
                    color="purple"
                    icon={<ArmoredSparkIcon status={nodeState.specFactory} />}
                  />
                </div>
              </div>

              {/* Vertical connection */}
              <div className="flex justify-center mb-6 mt-4">
                <VerticalConnectionLine active={connectionState.specToPlanner} />
              </div>

              {/* Bottom Row: Planner and Executor */}
              <div className="flex items-center gap-4 mt-8">
                <div className="relative">
                  <NodeModelSelector value={nodeModels.planner} onChange={v => setNodeModels(p => ({...p, planner: v}))} options={modelOptions} />
                  <WorkflowNode
                    title="PLANNER"
                    status={nodeState.planner}
                    color="emerald"
                    icon={<TeamIcon status={nodeState.planner} />}
                  />
                </div>
                <ConnectionLine active={connectionState.plannerToExecutor} />
                <div className="relative">
                  <NodeModelSelector value={nodeModels.executor} onChange={v => setNodeModels(p => ({...p, executor: v}))} options={modelOptions} />
                  <WorkflowNode
                    title="EXECUTOR"
                    status={nodeState.executor}
                    color="amber"
                    icon={<CodeIcon status={nodeState.executor} />}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Chat Resize Handle */}
          <div
            className="h-1 shrink-0 cursor-ns-resize group relative hover:bg-[#22d3ee]/30 transition-colors"
            onMouseDown={(e) => startDragging("chat", e)}
          >
            <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-4 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
              <GripHorizontal className="w-4 h-3 text-[#22d3ee]/60" />
            </div>
            <motion.div 
              className="absolute inset-x-0 top-0 h-px"
              style={{ background: "linear-gradient(to right, transparent, #22d3ee, transparent)" }}
              animate={{ opacity: isDragging === "chat" ? 1 : 0 }}
            />
          </div>

          {/* Chat Panel */}
          <div 
            className="border-t border-[#22d3ee]/30 flex flex-col shrink-0 bg-gradient-to-b from-[#0d0d12] to-[#0a0a0f] relative"
            style={{ height: chatHeight }}
          >
            {/* Glowing edge */}
            <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-[#22d3ee]/50 to-transparent" />
            
            <div className="px-4 py-2.5 border-b border-[#22d3ee]/20 flex items-center gap-2 bg-gradient-to-r from-[#22d3ee]/10 via-transparent to-transparent shrink-0">
              <motion.div
                animate={{ scale: [1, 1.2, 1] }}
                transition={{ duration: 1.5, repeat: Infinity }}
              >
                <Zap className="w-3.5 h-3.5 text-[#22d3ee]" style={{ filter: "drop-shadow(0 0 4px rgba(34,211,238,0.5))" }} />
              </motion.div>
              <span className="text-[10px] font-bold text-[#22d3ee] uppercase tracking-wider">Agent Chat (Control)</span>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-auto p-3 space-y-2 min-h-0">
              {chatMessages.map((msg, i) => (
                <ChatBubble key={i} message={msg} modelOptions={modelOptions} />
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* Input */}
            <form onSubmit={handleSubmit} className="p-3 border-t border-[#22d3ee]/20 shrink-0">
              <div 
                className="flex items-center gap-2 bg-[#0d0d12] rounded-lg px-4 py-2.5 border border-[#22d3ee]/30 transition-all focus-within:border-[#22d3ee]/60"
                style={{ boxShadow: "inset 0 0 20px rgba(0,0,0,0.5)" }}
              >
                <input
                  type="text"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  placeholder="Ask agent to build something..."
                  className="flex-1 bg-transparent outline-none text-xs placeholder:text-[#404040] text-[#cccccc]"
                  disabled={isSimulating}
                />
                <motion.button
                  type="submit"
                  disabled={isSimulating || !chatInput.trim()}
                  className="text-[#404040] hover:text-[#22d3ee] disabled:opacity-30 transition-colors"
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                >
                  <Send className="w-4 h-4" />
                </motion.button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

// File Tree Component with Cyberpunk Style
function FileTree({
  items,
  selectedFile,
  onSelectFile,
  onToggleFolder,
  onContextMenu,
  renamingPath,
  renameValue,
  setRenameValue,
  onRenameSubmit,
  onRenameCancel,
  path,
}: {
  items: FileItem[];
  selectedFile: string;
  onSelectFile: (name: string) => void;
  onToggleFolder: (path: string[]) => void;
  onContextMenu?: (e: React.MouseEvent, path: string, isDir: boolean) => void;
  renamingPath?: string | null;
  renameValue?: string;
  setRenameValue?: (v: string) => void;
  onRenameSubmit?: () => void;
  onRenameCancel?: () => void;
  path: string[];
}) {
  return (
    <div className="space-y-0.5">
      {items.map((item) => {
        const currentPath = [...path, item.name];
        // Strip root workspace folder from path for backend calls (skip first element = workspace name)
        const backendPath = currentPath.length > 1 ? currentPath.slice(1).join("/") : currentPath[0];
        const isRenaming = renamingPath === backendPath;

        return (
          <div key={item.name}>
            {item.type === "folder" ? (
              <>
                <motion.button
                  onClick={() => onToggleFolder(currentPath)}
                  onContextMenu={(e) => onContextMenu?.(e, backendPath, true)}
                  className="flex items-center gap-1.5 w-full px-2 py-1.5 rounded text-left hover:bg-[#22d3ee]/10 transition-colors group"
                  whileHover={{ x: 2 }}
                >
                  <ChevronRight
                    className={`w-3 h-3 text-[#22d3ee]/50 transition-transform group-hover:text-[#22d3ee] ${
                      item.expanded ? "rotate-90" : ""
                    }`}
                  />
                  {item.expanded ? (
                    <FolderOpen className="w-4 h-4 text-[#fbbf24]" style={{ filter: "drop-shadow(0 0 2px rgba(251,191,36,0.3))" }} />
                  ) : (
                    <Folder className="w-4 h-4 text-[#fbbf24]/70" />
                  )}
                  {isRenaming ? (
                    <input
                      className="text-xs bg-[#0a0a0f] border border-[#22d3ee]/60 rounded px-1 outline-none text-[#22d3ee] w-32"
                      value={renameValue}
                      autoFocus
                      onChange={(e) => setRenameValue?.(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") onRenameSubmit?.(); if (e.key === "Escape") onRenameCancel?.(); }}
                      onClick={(e) => e.stopPropagation()}
                    />
                  ) : (
                    <span className="text-xs text-[#808080] group-hover:text-[#cccccc]">{item.name}</span>
                  )}
                </motion.button>
                {item.expanded && item.children && (
                  <div className="ml-4 border-l border-[#22d3ee]/10 pl-1">
                    <FileTree
                      items={item.children}
                      selectedFile={selectedFile}
                      onSelectFile={onSelectFile}
                      onToggleFolder={onToggleFolder}
                      onContextMenu={onContextMenu}
                      renamingPath={renamingPath}
                      renameValue={renameValue}
                      setRenameValue={setRenameValue}
                      onRenameSubmit={onRenameSubmit}
                      onRenameCancel={onRenameCancel}
                      path={currentPath}
                    />
                  </div>
                )}
              </>
            ) : (
              <motion.button
                onClick={() => { if (!isRenaming) onSelectFile(backendPath); }}
                onContextMenu={(e) => onContextMenu?.(e, backendPath, false)}
                className={`flex items-center gap-1.5 w-full px-2 py-1.5 rounded text-left ml-4 transition-all ${
                  selectedFile === backendPath
                    ? "bg-[#22d3ee]/20 border border-[#22d3ee]/40"
                    : "hover:bg-[#22d3ee]/10"
                }`}
                style={selectedFile === backendPath ? { boxShadow: "0 0 10px rgba(34,211,238,0.2)" } : {}}
                whileHover={{ x: 2 }}
              >
                <FileText
                  className={`w-4 h-4 ${
                    item.name.endsWith(".py")
                      ? "text-[#22d3ee]"
                      : item.name.endsWith(".md")
                        ? "text-[#a855f7]"
                        : "text-[#808080]"
                  }`}
                  style={item.name.endsWith(".py") ? { filter: "drop-shadow(0 0 2px rgba(34,211,238,0.3))" } : {}}
                />
                {isRenaming ? (
                  <input
                    className="text-xs bg-[#0a0a0f] border border-[#22d3ee]/60 rounded px-1 outline-none text-[#22d3ee] w-32"
                    value={renameValue}
                    autoFocus
                    onChange={(e) => setRenameValue?.(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") onRenameSubmit?.(); if (e.key === "Escape") onRenameCancel?.(); }}
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <span className={`text-xs ${selectedFile === backendPath ? "text-[#22d3ee]" : "text-[#808080]"}`}>{item.name}</span>
                )}
              </motion.button>
            )}
          </div>
        );
      })}
    </div>
  );
}

// Code Editor with Syntax Highlighting and Cyberpunk Style
function CodeEditor({ content, filename }: { content: string; filename: string }) {
  const lines = content.split("\n");
  const isPython = filename.endsWith(".py");

  return (
    <div className="flex text-xs leading-6">
      {/* Line Numbers */}
      <div className="w-14 shrink-0 bg-[#0a0a0f] text-right pr-4 pt-3 select-none border-r border-[#22d3ee]/10">
        {lines.map((_, i) => (
          <div key={i} className="text-[#22d3ee]/30 hover:text-[#22d3ee]/60 transition-colors">
            {i + 1}
          </div>
        ))}
      </div>

      {/* Code */}
      <div className="flex-1 pt-3 pl-4 pr-4 overflow-x-auto">
        {lines.map((line, i) => (
          <motion.div 
            key={i} 
            className="whitespace-pre hover:bg-[#22d3ee]/5 transition-colors rounded"
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.02 }}
          >
            {isPython ? <PythonLine line={line} /> : line}
          </motion.div>
        ))}
      </div>
    </div>
  );
}

// Simple Python Syntax Highlighting with Neon Colors
function PythonLine({ line }: { line: string }) {
  const keywords = ["def", "return", "if", "import", "from", "class", "for", "while", "in", "and", "or", "not", "True", "False", "None", "assert"];
  
  const parts: { text: string; type: string }[] = [];
  let remaining = line;

  while (remaining.length > 0) {
    const stringMatch = remaining.match(/^(["'])(.*?)\1/);
    if (stringMatch) {
      parts.push({ text: stringMatch[0], type: "string" });
      remaining = remaining.slice(stringMatch[0].length);
      continue;
    }

    const fstringMatch = remaining.match(/^f(["'])(.*?)\1/);
    if (fstringMatch) {
      parts.push({ text: fstringMatch[0], type: "string" });
      remaining = remaining.slice(fstringMatch[0].length);
      continue;
    }

    if (remaining.startsWith("#")) {
      parts.push({ text: remaining, type: "comment" });
      break;
    }

    const funcMatch = remaining.match(/^(\w+)\(/);
    if (funcMatch) {
      const funcName = funcMatch[1];
      if (keywords.includes(funcName)) {
        parts.push({ text: funcName, type: "keyword" });
      } else {
        parts.push({ text: funcName, type: "function" });
      }
      remaining = remaining.slice(funcName.length);
      continue;
    }

    const wordMatch = remaining.match(/^(\w+)/);
    if (wordMatch) {
      const word = wordMatch[1];
      if (keywords.includes(word)) {
        parts.push({ text: word, type: "keyword" });
      } else if (word.match(/^[A-Z]/)) {
        parts.push({ text: word, type: "class" });
      } else {
        parts.push({ text: word, type: "normal" });
      }
      remaining = remaining.slice(word.length);
      continue;
    }

    const colonMatch = remaining.match(/^(:\s*)(\w+)/);
    if (colonMatch) {
      parts.push({ text: colonMatch[1], type: "normal" });
      parts.push({ text: colonMatch[2], type: "type" });
      remaining = remaining.slice(colonMatch[0].length);
      continue;
    }

    parts.push({ text: remaining[0], type: "normal" });
    remaining = remaining.slice(1);
  }

  return (
    <>
      {parts.map((part, i) => {
        const colorClass = {
          string: "text-[#fbbf24]", // Amber for strings
          comment: "text-[#34d399]/60", // Emerald for comments
          keyword: "text-[#a855f7]", // Purple for keywords
          function: "text-[#22d3ee]", // Cyan for functions
          class: "text-[#34d399]", // Emerald for classes
          type: "text-[#34d399]", // Emerald for types
          normal: "text-[#cccccc]",
        }[part.type];

        return (
          <span key={i} className={colorClass}>
            {part.text}
          </span>
        );
      })}
    </>
  );
}

// Model Selector Dropdown (Dual Provider/Model)
function NodeModelSelector({ 
  value, 
  onChange, 
  options 
}: { 
  value: string; 
  onChange: (val: string) => void; 
  options: {id: string, name: string, pricing?: any}[] 
}) {
  const currentCompany = value ? value.split('/')[0] : "";
  const companies = Array.from(new Set(options.map(o => o.id.split('/')[0]))).sort((a, b) => a.localeCompare(b));
  
  const handleCompanyChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newCompany = e.target.value;
    if (newCompany) {
       const firstModel = options.find(o => o.id.split('/')[0] === newCompany);
       if (firstModel) onChange(firstModel.id);
    } else {
       onChange("");
    }
  };

  const filteredOptions = currentCompany ? options.filter(o => o.id.split('/')[0] === currentCompany) : options;

  return (
    <div className="absolute -top-[54px] left-1/2 -translate-x-1/2 w-full min-w-[140px] max-w-[220px] px-2 z-20 flex flex-col gap-1.5">
      {/* Provider Dropdown */}
      <select 
        value={currentCompany} 
        onChange={handleCompanyChange}
        className="w-full text-[10px] bg-[#12121a] text-[#22d3ee] border border-[#22d3ee]/20 rounded px-1.5 py-0.5 outline-none cursor-pointer hover:border-[#22d3ee]/60 transition-colors uppercase font-semibold"
        style={{ boxShadow: "0 0 10px rgba(0,0,0,0.5)" }}
      >
        <option value="">PROVIDER...</option>
        {companies.map(c => <option key={c} value={c}>{c}</option>)}
      </select>
      
      {/* Model Dropdown */}
      <select 
        value={value} 
        onChange={e => onChange(e.target.value)}
        className="w-full text-[11px] bg-[#12121a] text-[#cccccc] border border-[#22d3ee]/30 rounded px-1.5 py-1 outline-none cursor-pointer hover:border-[#22d3ee]/60 transition-colors"
        disabled={!currentCompany}
        style={{ boxShadow: "0 0 10px rgba(0,0,0,0.5)" }}
      >
        <option value="">MODEL...</option>
        {filteredOptions.map(o => {
           let display = o.name;
           if (display.toLowerCase().startsWith(currentCompany.toLowerCase() + ":")) {
             display = display.substring(currentCompany.length + 1).trim();
           } else if (display.toLowerCase().startsWith(currentCompany.toLowerCase() + " ")) {
             display = display.substring(currentCompany.length + 1).trim();
           }
           return <option key={o.id} value={o.id}>{display}</option>;
         })}
      </select>
    </div>
  );
}

// Full Workflow Node with Glowing Effects
function WorkflowNode({
  title,
  status,
  color,
  icon,
}: {
  title: string;
  status: NodeStatus;
  color: "cyan" | "purple" | "emerald" | "amber";
  icon: React.ReactNode;
}) {
  const colorMap = {
    cyan: {
      glow: "0 0 30px rgba(34,211,238,0.6), 0 0 60px rgba(34,211,238,0.4), 0 0 90px rgba(34,211,238,0.2)",
      border: "#22d3ee",
      bg: "rgba(34,211,238,0.15)",
      text: "#22d3ee",
    },
    purple: {
      glow: "0 0 30px rgba(168,85,247,0.6), 0 0 60px rgba(168,85,247,0.4), 0 0 90px rgba(168,85,247,0.2)",
      border: "#a855f7",
      bg: "rgba(168,85,247,0.15)",
      text: "#a855f7",
    },
    emerald: {
      glow: "0 0 30px rgba(52,211,153,0.6), 0 0 60px rgba(52,211,153,0.4), 0 0 90px rgba(52,211,153,0.2)",
      border: "#34d399",
      bg: "rgba(52,211,153,0.15)",
      text: "#34d399",
    },
    amber: {
      glow: "0 0 30px rgba(251,191,36,0.6), 0 0 60px rgba(251,191,36,0.4), 0 0 90px rgba(251,191,36,0.2)",
      border: "#fbbf24",
      bg: "rgba(251,191,36,0.15)",
      text: "#fbbf24",
    },
  };

  const colors = colorMap[color];

  return (
    <motion.div
      className="relative w-[110px] h-[130px] rounded-xl transition-all duration-300"
      style={{
        border: `2px solid ${status === "idle" ? "#2d2d2d" : colors.border}`,
        background: status === "idle" ? "rgba(20,20,25,0.8)" : colors.bg,
        boxShadow: status === "active" ? colors.glow : status === "complete" ? `0 0 15px ${colors.border}40` : "none",
      }}
      animate={{
        scale: status === "active" ? 1.1 : 1,
      }}
      transition={{ type: "spring", stiffness: 300, damping: 20 }}
    >
      {/* Pulsing glow overlay when active */}
      <AnimatePresence>
        {status === "active" && (
          <motion.div
            className="absolute inset-0 rounded-xl"
            style={{ background: colors.bg }}
            initial={{ opacity: 0 }}
            animate={{ opacity: [0.3, 0.7, 0.3] }}
            exit={{ opacity: 0 }}
            transition={{ duration: 1.2, repeat: Infinity }}
          />
        )}
      </AnimatePresence>

      {/* Scanning line effect when active */}
      {status === "active" && (
        <motion.div
          className="absolute inset-x-0 h-0.5 rounded-full"
          style={{ background: `linear-gradient(90deg, transparent, ${colors.border}, transparent)` }}
          initial={{ top: 0 }}
          animate={{ top: ["0%", "100%", "0%"] }}
          transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
        />
      )}

      {/* Node Content */}
      <div className="relative z-10 flex flex-col items-center justify-center h-full p-3">
        {/* Icon Area */}
        <div className="w-12 h-12 flex items-center justify-center mb-3">{icon}</div>

        {/* Title */}
        <h3
          className="font-bold text-[9px] text-center tracking-wider transition-colors duration-300"
          style={{ color: status !== "idle" ? colors.text : "#606060" }}
        >
          {title}
        </h3>

        {/* Status Indicator */}
        <div className="absolute bottom-2.5 left-1/2 -translate-x-1/2">
          <motion.div
            className="w-2 h-2 rounded-full"
            style={{
              background: status === "idle" ? "#404040" : status === "complete" ? "#34d399" : colors.border,
              boxShadow: status !== "idle" ? `0 0 8px ${status === "complete" ? "#34d399" : colors.border}` : "none",
            }}
            animate={
              status === "active"
                ? {
                    scale: [1, 1.5, 1],
                    opacity: [1, 0.5, 1],
                  }
                : {}
            }
            transition={{ duration: 0.6, repeat: status === "active" ? Infinity : 0 }}
          />
        </div>
      </div>

      {/* Corner Accents */}
      {["top-0 left-0 border-t-2 border-l-2 rounded-tl-lg", "top-0 right-0 border-t-2 border-r-2 rounded-tr-lg", "bottom-0 left-0 border-b-2 border-l-2 rounded-bl-lg", "bottom-0 right-0 border-b-2 border-r-2 rounded-br-lg"].map((pos, i) => (
        <div
          key={i}
          className={`absolute w-4 h-4 ${pos} opacity-60`}
          style={{ borderColor: status !== "idle" ? colors.border : "#404040" }}
        />
      ))}
    </motion.div>
  );
}

// Horizontal Connection Line with Flowing Data Effect
function ConnectionLine({ active }: { active: boolean }) {
  return (
    <div className="relative w-16 h-4 flex items-center justify-center">
      {/* Base line */}
      <div className="absolute w-full h-0.5 bg-[#2d2d2d] rounded-full" />

      {/* Connector dots */}
      <div className="absolute left-0 w-2 h-2 rounded-full bg-[#2d2d2d]" />
      <div className="absolute right-0 w-2 h-2 rounded-full bg-[#2d2d2d]" />

      {/* Active pulse effect */}
      <AnimatePresence>
        {active && (
          <>
            {/* Glowing line */}
            <motion.div
              className="absolute w-full h-1 rounded-full"
              style={{ background: "linear-gradient(90deg, #22d3ee, #a855f7, #34d399)" }}
              initial={{ opacity: 0, scaleX: 0 }}
              animate={{ opacity: 1, scaleX: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
            />

            {/* Traveling pulse */}
            <motion.div
              className="absolute w-4 h-4 rounded-full blur-sm"
              style={{ background: "#22d3ee" }}
              initial={{ left: "-10%", opacity: 0 }}
              animate={{ left: "100%", opacity: [0, 1, 1, 0] }}
              transition={{ duration: 0.5, ease: "easeInOut" }}
            />

            {/* Core pulse */}
            <motion.div
              className="absolute w-2 h-2 rounded-full bg-white"
              initial={{ left: "-5%" }}
              animate={{ left: "95%" }}
              transition={{ duration: 0.5, ease: "easeInOut" }}
            />
          </>
        )}
      </AnimatePresence>
    </div>
  );
}

// Vertical Connection Line
function VerticalConnectionLine({ active }: { active: boolean }) {
  return (
    <div className="relative w-4 h-10 flex items-center justify-center">
      {/* Base line */}
      <div className="absolute h-full w-0.5 bg-[#2d2d2d] rounded-full" />

      {/* Active pulse effect */}
      <AnimatePresence>
        {active && (
          <>
            {/* Glowing line */}
            <motion.div
              className="absolute h-full w-1 rounded-full"
              style={{ background: "linear-gradient(180deg, #a855f7, #34d399)" }}
              initial={{ opacity: 0, scaleY: 0 }}
              animate={{ opacity: 1, scaleY: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
            />

            {/* Traveling pulse */}
            <motion.div
              className="absolute w-4 h-4 rounded-full blur-sm"
              style={{ background: "#a855f7" }}
              initial={{ top: "-10%", opacity: 0 }}
              animate={{ top: "100%", opacity: [0, 1, 1, 0] }}
              transition={{ duration: 0.4, ease: "easeInOut" }}
            />
          </>
        )}
      </AnimatePresence>
    </div>
  );
}

// Icon Components with Full Animations
function SparkIcon({ status }: { status: NodeStatus }) {
  return (
    <motion.div
      className="relative"
      animate={
        status === "active"
          ? { rotate: [0, 15, -15, 0] }
          : {}
      }
      transition={{ duration: 0.4, repeat: status === "active" ? Infinity : 0 }}
    >
      <Sparkles
        className="w-8 h-8 transition-colors duration-300"
        style={{
          color: status === "idle" ? "#606060" : status === "active" ? "#22d3ee" : "#22d3ee99",
          filter: status !== "idle" ? "drop-shadow(0 0 6px rgba(34,211,238,0.6))" : "none",
        }}
      />
      {status === "active" && (
        <motion.div
          className="absolute inset-0 flex items-center justify-center"
          animate={{ scale: [1, 1.5, 1], opacity: [0.5, 0, 0.5] }}
          transition={{ duration: 0.8, repeat: Infinity }}
        >
          <Sparkles className="w-8 h-8 text-[#22d3ee]" />
        </motion.div>
      )}
    </motion.div>
  );
}

function ArmoredSparkIcon({ status }: { status: NodeStatus }) {
  return (
    <div className="relative">
      <motion.div
        animate={
          status === "active"
            ? { rotateY: [0, 360] }
            : {}
        }
        transition={{ duration: 1.5, repeat: status === "active" ? Infinity : 0, ease: "linear" }}
        style={{ transformStyle: "preserve-3d" }}
      >
        <Shield
          className="w-8 h-8 transition-colors duration-300"
          style={{
            color: status === "idle" ? "#606060" : status === "active" ? "#a855f7" : "#a855f799",
            filter: status !== "idle" ? "drop-shadow(0 0 6px rgba(168,85,247,0.6))" : "none",
          }}
        />
      </motion.div>
      {/* Inner spark */}
      <div className="absolute inset-0 flex items-center justify-center">
        <Sparkles
          className="w-3 h-3 transition-colors duration-300"
          style={{ color: status === "idle" ? "#404040" : "#22d3ee" }}
        />
      </div>
      {/* Scanning laser effect */}
      {status === "active" && (
        <motion.div
          className="absolute inset-x-0 h-0.5"
          style={{ background: "linear-gradient(90deg, transparent, #a855f7, transparent)" }}
          animate={{ top: ["0%", "100%", "0%"] }}
          transition={{ duration: 1, repeat: Infinity }}
        />
      )}
    </div>
  );
}

function TeamIcon({ status }: { status: NodeStatus }) {
  return (
    <div className="relative flex items-center justify-center">
      <AnimatePresence mode="wait">
        {status === "idle" && (
          <motion.div
            key="single"
            initial={{ opacity: 1 }}
            exit={{ opacity: 0, scale: 0.8 }}
          >
            <Users className="w-8 h-8 text-[#606060]" />
          </motion.div>
        )}
        {(status === "active" || status === "complete") && (
          <motion.div
            key="team"
            initial={{ opacity: 0, scale: 0.5 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex items-end gap-0.5"
          >
            {[0, 1, 2].map((i) => (
              <motion.div
                key={i}
                initial={{ y: 15, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: i * 0.08 }}
              >
                <div
                  className="w-4 h-5 rounded-t-full border-2"
                  style={{
                    borderColor: status === "active" ? "#34d399" : "#34d39999",
                    background: status === "active" ? "rgba(52,211,153,0.2)" : "rgba(52,211,153,0.1)",
                    transform: i === 1 ? "scale(1.15)" : "scale(0.85)",
                    boxShadow: status === "active" ? "0 0 8px rgba(52,211,153,0.4)" : "none",
                  }}
                />
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
      {/* Holographic grid effect */}
      {status === "active" && (
        <motion.div
          className="absolute inset-0 rounded overflow-hidden"
          style={{
            background: "repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(52,211,153,0.15) 3px, rgba(52,211,153,0.15) 4px)",
          }}
          animate={{ y: [0, -4] }}
          transition={{ duration: 0.4, repeat: Infinity }}
        />
      )}
    </div>
  );
}

function CodeIcon({ status }: { status: NodeStatus }) {
  return (
    <div className="relative">
      <AnimatePresence mode="wait">
        {status === "idle" && (
          <motion.div key="idle" exit={{ opacity: 0, scale: 0.5 }}>
            <FileCode className="w-8 h-8 text-[#606060]" />
          </motion.div>
        )}
        {(status === "active" || status === "complete") && (
          <motion.div
            key="active"
            initial={{ opacity: 0, scale: 0.5 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex gap-0.5"
          >
            {[0, 1, 2].map((i) => (
              <motion.div
                key={i}
                initial={{ y: -15, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: i * 0.08 }}
              >
                <FileCode
                  className="w-5 h-6"
                  style={{
                    color: status === "active" ? "#fbbf24" : "#fbbf2499",
                    filter: status === "active" ? "drop-shadow(0 0 4px rgba(251,191,36,0.5))" : "none",
                  }}
                />
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
      {/* Terminal cursor blink */}
      {status === "active" && (
        <motion.div
          className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-4 h-0.5 rounded-full"
          style={{ background: "#fbbf24", boxShadow: "0 0 6px rgba(251,191,36,0.6)" }}
          animate={{ opacity: [1, 0, 1] }}
          transition={{ duration: 0.6, repeat: Infinity }}
        />
      )}
    </div>
  );
}

// Chat Bubble with Stage Colors
function ChatBubble({ 
  message, 
  modelOptions = [] 
}: { 
  message: ChatMessage; 
  modelOptions?: {id: string, name: string, pricing?: any}[] 
}) {
  const stageColors: Record<string, { color: string; glow: string }> = {
    origin: { color: "#22d3ee", glow: "0 0 10px rgba(34,211,238,0.3)" },
    specFactory: { color: "#a855f7", glow: "0 0 10px rgba(168,85,247,0.3)" },
    planner: { color: "#34d399", glow: "0 0 10px rgba(52,211,153,0.3)" },
    executor: { color: "#fbbf24", glow: "0 0 10px rgba(251,191,36,0.3)" },
  };

  const stageStyle = message.stage ? stageColors[message.stage] : null;

  let costStr = "";
  if (message.usage && message.usage.model) {
    const modelInfo = modelOptions.find(m => m.id === message.usage?.model);
    if (modelInfo && modelInfo.pricing) {
      const pCost = message.usage.prompt_tokens * parseFloat(modelInfo.pricing.prompt);
      const cCost = message.usage.completion_tokens * parseFloat(modelInfo.pricing.completion);
      const total = pCost + cCost;
      if (!isNaN(total)) costStr = `Cost: $${total.toFixed(6)}`;
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`text-xs ${message.role === "user" ? "text-right" : "text-left"}`}
    >
      {message.role === "user" ? (
        <span 
          className="inline-block px-3 py-1.5 rounded-lg"
          style={{ 
            background: "linear-gradient(135deg, rgba(34,211,238,0.2) 0%, rgba(168,85,247,0.2) 100%)",
            border: "1px solid rgba(34,211,238,0.3)",
          }}
        >
          {message.content}
        </span>
      ) : (
        <div
          className="inline-block"
          style={{ color: stageStyle?.color || "#808080" }}
        >
          {message.stage && (
            <motion.span
              className="inline-block w-1.5 h-1.5 rounded-full mr-2"
              style={{ background: stageStyle?.color, boxShadow: stageStyle?.glow }}
              animate={{ opacity: [1, 0.3, 1] }}
              transition={{ duration: 0.6, repeat: Infinity }}
            />
          )}
          <span>{message.content}</span>
          
          {message.usage && (
            <div className="mt-2 pt-2 border-t border-[#808080]/20 flex flex-wrap items-center gap-3 text-[9px] font-mono">
              <span className="text-[#34d399]">In: {message.usage.prompt_tokens}</span>
              <span className="text-[#a855f7]">Out: {message.usage.completion_tokens}</span>
              {costStr && <span className="text-[#fbbf24]">{costStr}</span>}
              <span className="text-[#808080]/60 ml-auto break-all">{message.usage.model}</span>
            </div>
          )}
        </div>
      )}
    </motion.div>
  );
}
