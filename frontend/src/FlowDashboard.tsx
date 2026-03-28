import { useEffect } from 'react';
import {
  ReactFlow,
  Background,
  useNodesState,
  useEdgesState,
  type NodeProps,
  Handle,
  Position,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

// SVG Assets
const StickFigure = () => (
  <svg width="24" height="40" viewBox="0 0 24 40" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="8" r="4" />
    <path d="M12 12V24M12 16H6M12 16H18M12 24L8 32M12 24L16 32" />
  </svg>
);

const Shield = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
);

const Factory = () => (
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
    <path d="M2 20h20M4 20V8l6 3V6l6 3v11M16 20V4l6 3v13" />
    <path d="M6 20v-4h2v4M12 20v-4h2v4" />
  </svg>
);

const FileIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" />
  </svg>
);

// Custom Nodes
const IdeaNode = ({ data }: NodeProps) => {
  return (
    <div className={`p-4 rounded-lg border-2 shadow-lg bg-[#252526] flex flex-col items-center justify-center transition-all ${data.status === 'active' ? 'border-yellow-400 ring-4 ring-yellow-400/20' : data.status === 'complete' ? 'border-green-500' : 'border-[#333]'}`}>
      <Handle type="target" position={Position.Left} className="opacity-0" />
      <div className="text-gray-300 mb-2 font-bold text-sm tracking-widest uppercase">Idea</div>
      <div className={`text-blue-400 ${data.status === 'active' ? 'animate-bounce' : ''}`}>
        <StickFigure />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
};

const SpecNode = ({ data }: NodeProps) => {
  return (
    <div className={`p-4 rounded-lg border-2 shadow-lg bg-[#252526] flex flex-col items-center justify-center transition-all ${data.status === 'active' ? 'border-yellow-400 ring-4 ring-yellow-400/20' : data.status === 'complete' ? 'border-green-500' : 'border-[#333]'}`}>
      <Handle type="target" position={Position.Left} />
      <div className="text-gray-300 mb-2 font-bold text-sm tracking-widest uppercase">Spec Factory</div>
      <div className="flex items-center gap-4">
        <div className={`text-orange-400 ${data.status === 'active' ? 'animate-pulse' : ''}`}>
          <Factory />
        </div>
        {data.status === 'complete' && (
          <div className="flex items-center text-purple-400 animate-in fade-in zoom-in duration-300">
            <StickFigure />
            <div className="text-yellow-400 -ml-2 -mt-4"><Shield /></div>
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
};

const PlannerNode = ({ data }: NodeProps) => {
  return (
    <div className={`p-4 rounded-lg border-2 shadow-lg bg-[#252526] flex flex-col items-center justify-center transition-all ${data.status === 'active' ? 'border-yellow-400 ring-4 ring-yellow-400/20' : data.status === 'complete' ? 'border-green-500' : 'border-[#333]'}`}>
      <Handle type="target" position={Position.Left} />
      <div className="text-gray-300 mb-2 font-bold text-sm tracking-widest uppercase">Planner</div>
      <div className="flex flex-col items-center gap-2">
        <div className="flex items-center text-purple-400 opacity-50">
          <StickFigure />
          <div className="text-yellow-400 -ml-2 -mt-4"><Shield /></div>
        </div>
        {data.status === 'complete' && (
          <div className="flex gap-2 text-cyan-400 animate-in slide-in-from-top-4 duration-500">
            <div className="scale-75"><StickFigure /></div>
            <div className="scale-75"><StickFigure /></div>
            <div className="scale-75"><StickFigure /></div>
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
};

const ExecutorNode = ({ data }: NodeProps) => {
  return (
    <div className={`p-4 rounded-lg border-2 shadow-lg bg-[#252526] flex flex-col items-center justify-center transition-all ${data.status === 'active' ? 'border-yellow-400 ring-4 ring-yellow-400/20' : data.status === 'complete' ? 'border-green-500' : 'border-[#333]'}`}>
      <Handle type="target" position={Position.Left} />
      <div className="text-gray-300 mb-2 font-bold text-sm tracking-widest uppercase">Executor</div>
      <div className="flex items-center gap-4">
        <div className="flex flex-col items-center gap-1 text-cyan-400 opacity-50 scale-75">
          <StickFigure />
          <StickFigure />
        </div>
        {data.status === 'complete' && (
          <div className="flex gap-2 text-emerald-400 animate-in zoom-in duration-500">
            <FileIcon />
            <FileIcon />
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="opacity-0" />
    </div>
  );
};

const nodeTypes = {
  ideaNode: IdeaNode,
  specNode: SpecNode,
  plannerNode: PlannerNode,
  executorNode: ExecutorNode,
};

const initialNodes = [
  { id: 'idea', position: { x: 50, y: 150 }, data: { status: 'idle' }, type: 'ideaNode' },
  { id: 'spec_factory', position: { x: 300, y: 150 }, data: { status: 'idle' }, type: 'specNode' },
  { id: 'planner', position: { x: 600, y: 150 }, data: { status: 'idle' }, type: 'plannerNode' },
  { id: 'executor', position: { x: 880, y: 150 }, data: { status: 'idle' }, type: 'executorNode' },
];

const initialEdges = [
  { id: 'e-idea-spec', source: 'idea', target: 'spec_factory', animated: false, style: { stroke: '#4b5563', strokeWidth: 2 } },
  { id: 'e-spec-planner', source: 'spec_factory', target: 'planner', animated: false, style: { stroke: '#4b5563', strokeWidth: 2 } },
  { id: 'e-planner-executor', source: 'planner', target: 'executor', animated: false, style: { stroke: '#4b5563', strokeWidth: 2 } },
];

export default function FlowDashboard({ stationsStatus }: { stationsStatus: Record<string, string> }) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    // Update nodes status based on props
    setNodes((nds) => 
      nds.map((n) => {
        return {
          ...n,
          data: {
            ...n.data,
            status: stationsStatus[n.id] || 'idle'
          }
        };
      })
    );

    // Update edges animation
    setEdges((eds) => 
      eds.map((e) => {
        let animated = false;
        let stroke = '#4b5563';
        
        // Edge idea -> spec
        if (e.id === 'e-idea-spec') {
          if (stationsStatus['idea'] === 'complete' && stationsStatus['spec_factory'] !== 'complete') animated = true;
          if (stationsStatus['idea'] === 'complete') stroke = '#3b82f6';
        }
        // Edge spec -> planner
        if (e.id === 'e-spec-planner') {
          if (stationsStatus['spec_factory'] === 'complete' && stationsStatus['planner'] !== 'complete') animated = true;
          if (stationsStatus['spec_factory'] === 'complete') stroke = '#8b5cf6';
        }
        // Edge planner -> executor
        if (e.id === 'e-planner-executor') {
          if (stationsStatus['planner'] === 'complete' && stationsStatus['executor'] !== 'complete') animated = true;
          if (stationsStatus['planner'] === 'complete') stroke = '#10b981';
        }

        return {
          ...e,
          animated,
          style: { stroke, strokeWidth: animated ? 3 : 2 }
        };
      })
    );
  }, [stationsStatus, setNodes, setEdges]);

  return (
    <div className="w-full h-full bg-[#1e1e1e]">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        className="pointer-events-none" // Optional: makes graph static/non-interactive
      >
        <Background color="#333" gap={16} />
      </ReactFlow>
    </div>
  );
}
