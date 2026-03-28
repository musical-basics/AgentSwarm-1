"use client";

import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

export function TerminalPanel() {
  const terminalRef = useRef<HTMLDivElement>(null);
  const termInstance = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!terminalRef.current) return;

    // Initialize xterm
    const term = new Terminal({
      theme: {
        background: "#0a0a0f",
        foreground: "#cccccc",
        cursor: "#22d3ee",
        selectionBackground: "rgba(34,211,238,0.3)",
      },
      fontFamily: "Menlo, Monaco, 'Courier New', monospace",
      fontSize: 12,
      cursorBlink: true,
    });
    termInstance.current = term;

    const fitAddon = new FitAddon();
    fitAddonRef.current = fitAddon;
    term.loadAddon(fitAddon);

    term.open(terminalRef.current);
    let fitTimeout: any;
    const initialFit = () => {
      try {
        fitAddon.fit();
        if (term.cols < 10) {
          fitTimeout = setTimeout(initialFit, 50);
        }
      } catch (e) {}
    };
    initialFit();

    // Resize observer
    const resizeObserver = new ResizeObserver(() => {
      try {
        fitAddon.fit();
      } catch (e) {
        // safe ignore resizing errors when unmounting
      }
    });
    resizeObserver.observe(terminalRef.current);

    // WebSocket connect
    const connect = () => {
      const ws = new WebSocket("ws://127.0.0.1:6500/pty");
      wsRef.current = ws;

      ws.onopen = () => {
        term.write("\r\n\x1b[36m❖ Flowmind PTY Terminal Initialized\x1b[0m\r\n\r\n");
        // Send initial resize
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      };

      ws.onmessage = (e) => {
        if (typeof e.data === "string") {
          term.write(e.data);
        } else {
           const reader = new FileReader();
           reader.onload = () => {
             term.write(new Uint8Array(reader.result as ArrayBuffer));
           };
           reader.readAsArrayBuffer(e.data);
        }
      };

      ws.onclose = () => {
        term.write("\r\n\x1b[31m[Process Exited] Connection closed.\x1b[0m\r\n");
      };

      ws.onerror = () => {
        // term.write("\r\n\x1b[31m[WebSocket connection failed...]\x1b[0m\r\n");
      };

      term.onResize(({ cols, rows }) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "resize", cols, rows }));
        }
      });

      // Send keystrokes directly to Python PTY over websocket
      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "input", data }));
        }
      });
    };

    connect();

    return () => {
      resizeObserver.disconnect();
      term.dispose();
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  return (
    <div className="w-full h-full bg-[#0a0a0f] pt-2 px-2 pb-0 overflow-hidden border-t border-[#22d3ee]/20 flex flex-col">
      <div className="flex items-center gap-2 mb-2 px-1 shrink-0">
         <span className="w-2 h-2 rounded-full bg-[#22d3ee] animate-pulse shadow-[0_0_8px_rgba(34,211,238,0.8)]"></span>
         <span className="text-[10px] font-bold text-[#22d3ee] uppercase tracking-wider">Local Terminal</span>
      </div>
      <div className="relative flex-1 min-h-0 min-w-0 w-full overflow-hidden">
        <div ref={terminalRef} className="absolute inset-0" />
      </div>
    </div>
  );
}
