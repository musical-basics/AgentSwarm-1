const fs = require('fs');

let content = fs.readFileSync('../_v0_frontend/components/flowmind/flowmind-ide.tsx', 'utf-8');

// Strip "use client"
content = content.replace('"use client";\n', '');

// Add type declarations and Monaco
content = content.replace(
  'export function FlowmindIDE() {',
  `declare global {
  interface Window {
    electronAPI?: {
      openDirectory: () => Promise<string | null>;
    };
  }
}

import Editor from "@monaco-editor/react";

export default function App() {
`
);

// Add Socket and File Cache State
content = content.replace(
  'const [nodeState, setNodeState] = useState<NodeState>({',
  `const [socket, setSocket] = useState<WebSocket | null>(null);
  const [fileContentsCache, setFileContentsCache] = useState<Record<string, string>>({});
  const [nodeState, setNodeState] = useState<NodeState>({`
);

// Inject WebSocket useEffect
const wsLogic = `
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
          const processFiles = (list: any[]): FileItem[] => {
            return list.map((f: any) => ({
               name: f.name,
               type: f.is_dir ? ("folder" as const) : ("file" as const),
               children: [], 
               expanded: false
            }));
          };
          setFiles([{
            name: "Active Workspace",
            type: "folder" as const,
            expanded: true,
            children: processFiles(data.files || [])
          }]);
        } else if (data.event === "file_content") {
          setFileContentsCache(prev => ({ ...prev, [data.path]: data.content }));
          setSelectedFile(data.path);
        } else if (data.event === "chat") {
          setChatMessages(prev => [...prev, { role: data.sender === "swarm" ? ("agent" as const) : ("user" as const), content: data.text, stage: data.stage }]);
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
          setChatMessages(prev => [...prev, { role: "agent" as const, content: "Swarm workflow complete! Ready for next task." }]);
        } else if (data.event === "error") {
          console.error(data.message);
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
    if (window.electronAPI) {
      const folderPath = await window.electronAPI.openDirectory();
      if (folderPath && socket) {
        socket.send(JSON.stringify({ command: "set_workspace", path: folderPath }));
      }
    } else {
      alert("Please run inside electron to open folders.");
    }
  };
`;

content = content.replace('const dragStartRef = useRef({ x: 0, y: 0, value: 0 });', 'const dragStartRef = useRef({ x: 0, y: 0, value: 0 });\\n' + wsLogic);

const simStart = content.indexOf('const simulateSwarm = useCallback(async ');
if (simStart !== -1) {
  const simEnd = content.indexOf('}, [isSimulating]);', simStart);
  if (simEnd !== -1) {
    content = content.substring(0, simStart) + content.substring(simEnd + 19);
  }
}

// Modify handleSubmit and simulate dispatch
content = content.replace(
  'simulateSwarm(chatInput.trim());',
  'if (socket) socket.send(JSON.stringify({ command: "swarm_message", message: chatInput.trim() }));'
);

content = content.replace(
  /onClick=\{\(\) => simulateSwarm\(\)\}/g,
  'onClick={() => { if (chatInput.trim() && socket) socket.send(JSON.stringify({ command: "swarm_message", message: chatInput.trim() })); else alert("Type a message to simulate swarm"); }}'
);

// Map strictly backend logic for selecting files
content = content.replace(
  'onSelectFile={setSelectedFile}',
  'onSelectFile={(name) => { setSelectedFile(name); if (socket) socket.send(JSON.stringify({ command: "read_file", path: name })); }}'
);

// Update Header to have FolderOpen icon
const origHeader = '<span className="text-[10px] font-semibold text-[#22d3ee] uppercase tracking-wider">\\n                Workspace Sandbox\\n              </span>';
const newHeader = `<div className="flex-1 flex justify-between items-center pr-2">
                <span className="text-[10px] font-semibold text-[#22d3ee] uppercase tracking-wider">WORKSPACE SANDBOX</span>
                <button onClick={handleOpenFolder} className="text-[#22d3ee] hover:text-white" title="Open Folder"><FolderOpen className="w-3.5 h-3.5" /></button>
              </div>`;
content = content.replace(origHeader, newHeader);

const codeRegex = /<CodeEditor[\s\S]*?\/>/g;
const newEditor = `
              <Editor
                height="100%"
                theme="vs-dark"
                path={selectedFile}
                value={fileContentsCache[selectedFile] || "// Loading..."}
                options={{ readOnly: true, minimap: { enabled: false }, fontFamily: "Menlo, Monaco, 'Courier New', monospace" }}
              />
`;
content = content.replace(codeRegex, newEditor);

fs.writeFileSync('src/App.tsx', content, 'utf-8');
console.log('Migration successful');
