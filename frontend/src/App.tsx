import { useEffect, useState, useRef } from "react";
import Editor from "@monaco-editor/react";
import { Allotment } from "allotment";
import "allotment/dist/style.css";
import { FileCode2, Command } from "lucide-react";

type FileNode = {
  name: string;
  path: string;
  is_dir: boolean;
};

type ChatMessage = {
  sender: "user" | "swarm";
  text: string;
};

export default function App() {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [files, setFiles] = useState<FileNode[]>([]);
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [inputVal, setInputVal] = useState("");
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let ws: WebSocket;
    
    const connect = () => {
      ws = new WebSocket("ws://127.0.0.1:8000/ws");
      
      ws.onopen = () => {
        console.log("Connected to backend");
        setSocket(ws);
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "file_list") {
          setFiles(data.files || []);
        } else if (data.type === "file_content") {
          setActiveFile(data.path);
          setFileContent(data.content);
        } else if (data.type === "chat") {
          setChatHistory(prev => [...prev, { sender: data.sender, text: data.text }]);
        } else if (data.type === "monaco_update") {
          setActiveFile(data.path);
          setFileContent(data.content);
        } else if (data.type === "error") {
          console.error(data.message);
        }
      };

      ws.onclose = () => {
        console.log("Disconnected, retrying...");
        setTimeout(connect, 3000);
      };
    };
    
    connect();
    
    return () => {
      ws?.close();
    };
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory]);

  const loadFile = (path: string) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ command: "read_file", path }));
    }
  };

  const handleSend = () => {
    if (!inputVal.trim() || !socket) return;
    socket.send(JSON.stringify({ command: "swarm_message", message: inputVal }));
    setInputVal("");
  };

  return (
    <div className="w-full h-full flex flex-col bg-[#1e1e1e] text-white overflow-hidden">
      <header className="h-10 bg-[#333] flex items-center px-4 shrink-0 text-sm font-semibold select-none shadow-md z-10">
        <Command size={18} className="text-blue-400 mr-2" />
        AgentSwarm Local IDE
      </header>
      <div className="flex-1 w-full relative">
        <Allotment className="allotment-override">
          <Allotment.Pane minSize={200} maxSize={300}>
            <div className="h-full bg-[#181818] border-r border-[#333] flex flex-col pt-2">
              <div className="px-3 pb-2 text-xs font-bold text-gray-400 uppercase tracking-wider">
                Workspace Sandbox
              </div>
              <div className="flex-1 overflow-auto p-2">
                {files.map((f, i) => (
                  <div 
                    key={i} 
                    className={`p-1.5 text-sm cursor-pointer rounded flex items-center gap-2 select-none mb-1
                      ${activeFile === f.path ? "bg-[#37373d]" : "hover:bg-[#2a2d2e]"}
                    `}
                    onClick={() => !f.is_dir && loadFile(f.path)}
                  >
                    <FileCode2 size={16} className={f.is_dir ? "text-yellow-400" : "text-blue-400"} />
                    <span className="truncate" title={f.name}>{f.name}</span>
                  </div>
                ))}
              </div>
            </div>
          </Allotment.Pane>
          <Allotment.Pane>
            <Allotment>
              <Allotment.Pane minSize={300} preferredSize="40%" className="border-r border-[#333]">
                <div className="h-full flex flex-col">
                  <div className="px-4 py-2 bg-[#252526] text-xs font-semibold text-gray-400 border-b border-[#333]">
                    AGENT CHAT
                  </div>
                  <div className="flex-1 p-4 overflow-auto flex flex-col gap-4">
                    {chatHistory.length === 0 && (
                      <div className="text-center text-gray-500 mt-10 text-sm">
                        Send a message to the swarm simulator.
                      </div>
                    )}
                    {chatHistory.map((msg, i) => (
                      <div key={i} className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`p-3 max-w-[85%] rounded text-sm shadow-md text-gray-100 ${
                          msg.sender === 'user' 
                          ? 'bg-blue-600 rounded-tr-sm' 
                          : 'bg-[#2a2d2e] rounded-tl-sm border border-[#3c3f41] text-gray-300'
                        }`}>
                          {msg.text}
                        </div>
                      </div>
                    ))}
                    <div ref={chatEndRef} />
                  </div>
                  <div className="p-4 bg-[#252526] border-t border-[#333]">
                    <input
                      type="text"
                      className="w-full bg-[#1e1e1e] text-white p-3 text-sm rounded outline-none border border-[#3c3f41] focus:border-blue-500 transition-colors shadow-inner"
                      placeholder="Ask agent to build something..."
                      value={inputVal}
                      onChange={(e) => setInputVal(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleSend()}
                    />
                  </div>
                </div>
              </Allotment.Pane>
              <Allotment.Pane minSize={400}>
                <div className="h-full flex flex-col bg-[#1e1e1e]">
                  <div className="px-4 py-2 bg-[#1e1e1e] text-xs font-mono text-gray-400 border-b border-[#333]">
                    {activeFile ? activeFile : "No file selected"}
                  </div>
                  <div className="flex-1 p-2">
                    {activeFile ? (
                      <Editor
                        height="100%"
                        theme="vs-dark"
                        path={activeFile}
                        value={fileContent}
                        options={{ 
                          readOnly: true, 
                          minimap: { enabled: false },
                          fontSize: 14,
                          fontFamily: "Menlo, Monaco, 'Courier New', monospace"
                        }}
                      />
                    ) : (
                      <div className="h-full flex items-center justify-center text-gray-600 text-sm select-none">
                        Select a file from the sidebar to view code
                      </div>
                    )}
                  </div>
                </div>
              </Allotment.Pane>
            </Allotment>
          </Allotment.Pane>
        </Allotment>
      </div>
    </div>
  );
}
