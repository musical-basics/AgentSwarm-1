"use client";

import { useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, Shield, Users, FileCode, Zap, Play } from "lucide-react";
import { Button } from "@/components/ui/button";

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

export function AgentSwarmWorkflow() {
  const [nodeState, setNodeState] = useState<NodeState>({
    origin: "idle",
    specFactory: "idle",
    planner: "idle",
    executor: "idle",
  });

  const [connectionState, setConnectionState] = useState<ConnectionState>({
    originToSpec: false,
    specToPlanner: false,
    plannerToExecutor: false,
  });

  const [isSimulating, setIsSimulating] = useState(false);

  const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

  const simulateSwarm = useCallback(async () => {
    if (isSimulating) return;
    setIsSimulating(true);

    // Reset all states
    setNodeState({
      origin: "idle",
      specFactory: "idle",
      planner: "idle",
      executor: "idle",
    });
    setConnectionState({
      originToSpec: false,
      specToPlanner: false,
      plannerToExecutor: false,
    });

    await delay(300);

    // Step 1: Origin lights up
    setNodeState((prev) => ({ ...prev, origin: "active" }));
    await delay(800);

    // Step 2: Connection to Spec Factory pulses
    setConnectionState((prev) => ({ ...prev, originToSpec: true }));
    await delay(600);

    // Step 3: Origin complete, Spec Factory active
    setNodeState((prev) => ({ ...prev, origin: "complete", specFactory: "active" }));
    await delay(800);

    // Step 4: Connection to Planner pulses
    setConnectionState((prev) => ({ ...prev, specToPlanner: true }));
    await delay(600);

    // Step 5: Spec Factory complete, Planner active
    setNodeState((prev) => ({ ...prev, specFactory: "complete", planner: "active" }));
    await delay(800);

    // Step 6: Connection to Executor pulses
    setConnectionState((prev) => ({ ...prev, plannerToExecutor: true }));
    await delay(600);

    // Step 7: Planner complete, Executor active
    setNodeState((prev) => ({ ...prev, planner: "complete", executor: "active" }));
    await delay(800);

    // Step 8: All complete
    setNodeState((prev) => ({ ...prev, executor: "complete" }));
    await delay(500);

    setIsSimulating(false);
  }, [isSimulating]);

  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-background">
      {/* Grid Background */}
      <div
        className="absolute inset-0 opacity-20"
        style={{
          backgroundImage: `
            radial-gradient(circle at 1px 1px, var(--neon-cyan) 1px, transparent 0)
          `,
          backgroundSize: "32px 32px",
        }}
      />

      {/* Ambient Glow */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-neon-cyan/5 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-neon-purple/5 rounded-full blur-3xl" />
      </div>

      <div className="relative z-10 flex flex-col items-center justify-center min-h-screen p-8">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center mb-12"
        >
          <h1 className="text-3xl md:text-4xl font-bold text-foreground tracking-tight mb-2">
            <span className="text-neon-cyan">Flowmind</span> IDE
          </h1>
          <p className="text-muted-foreground font-mono text-sm">
            AI Agent Swarm Workflow Visualizer
          </p>
        </motion.div>

        {/* Workflow Graph */}
        <div className="flex flex-col lg:flex-row items-center justify-center gap-4 lg:gap-0 w-full max-w-6xl">
          {/* Node 1: Origin */}
          <WorkflowNode
            title="The Origin"
            subtitle="Idea"
            status={nodeState.origin}
            color="cyan"
            icon={<SparkIcon status={nodeState.origin} />}
          />

          {/* Connection 1 */}
          <ConnectionLine active={connectionState.originToSpec} />

          {/* Node 2: Spec Factory */}
          <WorkflowNode
            title="Spec Factory"
            subtitle="Requirements"
            status={nodeState.specFactory}
            color="purple"
            icon={<ArmoredSparkIcon status={nodeState.specFactory} />}
          />

          {/* Connection 2 */}
          <ConnectionLine active={connectionState.specToPlanner} />

          {/* Node 3: Planner Station */}
          <WorkflowNode
            title="Planner Station"
            subtitle="Architecture"
            status={nodeState.planner}
            color="emerald"
            icon={<TeamIcon status={nodeState.planner} />}
          />

          {/* Connection 3 */}
          <ConnectionLine active={connectionState.plannerToExecutor} />

          {/* Node 4: Executor */}
          <WorkflowNode
            title="Executor"
            subtitle="Implementation"
            status={nodeState.executor}
            color="amber"
            icon={<CodeIcon status={nodeState.executor} />}
          />
        </div>

        {/* Simulate Button */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="mt-16"
        >
          <Button
            onClick={simulateSwarm}
            disabled={isSimulating}
            size="lg"
            className="relative overflow-hidden bg-secondary hover:bg-secondary/80 text-foreground border border-neon-cyan/50 hover:border-neon-cyan px-8 py-6 text-lg font-mono group"
          >
            <motion.div
              className="absolute inset-0 bg-gradient-to-r from-neon-cyan/20 via-neon-purple/20 to-neon-emerald/20"
              animate={{
                x: isSimulating ? ["0%", "100%"] : "0%",
              }}
              transition={{
                duration: 1,
                repeat: isSimulating ? Infinity : 0,
                ease: "linear",
              }}
            />
            <span className="relative flex items-center gap-3">
              {isSimulating ? (
                <>
                  <Zap className="w-5 h-5 animate-pulse text-neon-cyan" />
                  Simulating...
                </>
              ) : (
                <>
                  <Play className="w-5 h-5 group-hover:text-neon-cyan transition-colors" />
                  Simulate Swarm
                </>
              )}
            </span>
          </Button>
        </motion.div>
      </div>
    </div>
  );
}

// Workflow Node Component
function WorkflowNode({
  title,
  subtitle,
  status,
  color,
  icon,
}: {
  title: string;
  subtitle: string;
  status: NodeStatus;
  color: "cyan" | "purple" | "emerald" | "amber";
  icon: React.ReactNode;
}) {
  const colorMap = {
    cyan: {
      glow: "shadow-[0_0_30px_rgba(34,211,238,0.3)]",
      border: "border-neon-cyan",
      bg: "bg-neon-cyan/10",
      text: "text-neon-cyan",
    },
    purple: {
      glow: "shadow-[0_0_30px_rgba(168,85,247,0.3)]",
      border: "border-neon-purple",
      bg: "bg-neon-purple/10",
      text: "text-neon-purple",
    },
    emerald: {
      glow: "shadow-[0_0_30px_rgba(52,211,153,0.3)]",
      border: "border-neon-emerald",
      bg: "bg-neon-emerald/10",
      text: "text-neon-emerald",
    },
    amber: {
      glow: "shadow-[0_0_30px_rgba(251,191,36,0.3)]",
      border: "border-neon-amber",
      bg: "bg-neon-amber/10",
      text: "text-neon-amber",
    },
  };

  const colors = colorMap[color];

  return (
    <motion.div
      className={`
        relative w-48 h-56 rounded-xl border-2 transition-all duration-300
        ${status === "idle" ? "border-border bg-card" : ""}
        ${status === "active" ? `${colors.border} ${colors.bg} ${colors.glow}` : ""}
        ${status === "complete" ? `${colors.border} ${colors.bg} opacity-80` : ""}
      `}
      animate={{
        scale: status === "active" ? 1.05 : 1,
      }}
      transition={{ type: "spring", stiffness: 300, damping: 20 }}
    >
      {/* Pulsing glow effect when active */}
      <AnimatePresence>
        {status === "active" && (
          <motion.div
            className={`absolute inset-0 rounded-xl ${colors.bg}`}
            initial={{ opacity: 0 }}
            animate={{ opacity: [0.3, 0.6, 0.3] }}
            exit={{ opacity: 0 }}
            transition={{ duration: 1.5, repeat: Infinity }}
          />
        )}
      </AnimatePresence>

      {/* Node Content */}
      <div className="relative z-10 flex flex-col items-center justify-center h-full p-4">
        {/* Icon Area */}
        <div className="w-20 h-20 flex items-center justify-center mb-4">{icon}</div>

        {/* Title */}
        <h3
          className={`font-bold text-sm text-center transition-colors duration-300 ${
            status !== "idle" ? colors.text : "text-foreground"
          }`}
        >
          {title}
        </h3>
        <p className="text-xs text-muted-foreground font-mono mt-1">{subtitle}</p>

        {/* Status Indicator */}
        <div className="absolute bottom-3 left-1/2 -translate-x-1/2">
          <motion.div
            className={`w-2 h-2 rounded-full ${
              status === "idle"
                ? "bg-muted-foreground/50"
                : status === "active"
                  ? `bg-current ${colors.text}`
                  : "bg-neon-emerald"
            }`}
            animate={
              status === "active"
                ? {
                    scale: [1, 1.5, 1],
                    opacity: [1, 0.5, 1],
                  }
                : {}
            }
            transition={{ duration: 0.8, repeat: status === "active" ? Infinity : 0 }}
          />
        </div>
      </div>

      {/* Corner Accents */}
      <div className={`absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 rounded-tl-lg ${colors.border} opacity-50`} />
      <div className={`absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 rounded-tr-lg ${colors.border} opacity-50`} />
      <div className={`absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 rounded-bl-lg ${colors.border} opacity-50`} />
      <div className={`absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 rounded-br-lg ${colors.border} opacity-50`} />
    </motion.div>
  );
}

// Connection Line with flowing data effect
function ConnectionLine({ active }: { active: boolean }) {
  return (
    <div className="relative w-24 lg:w-20 h-8 lg:h-2 flex items-center justify-center rotate-90 lg:rotate-0">
      {/* Base line */}
      <div className="absolute w-full h-0.5 bg-border rounded-full" />

      {/* Active pulse effect */}
      <AnimatePresence>
        {active && (
          <>
            {/* Glowing line */}
            <motion.div
              className="absolute w-full h-0.5 bg-gradient-to-r from-neon-cyan via-neon-purple to-neon-emerald rounded-full"
              initial={{ opacity: 0, scaleX: 0 }}
              animate={{ opacity: 1, scaleX: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
            />

            {/* Traveling pulse */}
            <motion.div
              className="absolute w-4 h-4 rounded-full bg-neon-cyan blur-sm"
              initial={{ x: "-100%", opacity: 0 }}
              animate={{ x: "400%", opacity: [0, 1, 1, 0] }}
              transition={{ duration: 0.6, ease: "easeInOut" }}
            />

            {/* Secondary pulse */}
            <motion.div
              className="absolute w-2 h-2 rounded-full bg-foreground"
              initial={{ x: "-100%" }}
              animate={{ x: "800%" }}
              transition={{ duration: 0.6, ease: "easeInOut" }}
            />
          </>
        )}
      </AnimatePresence>
    </div>
  );
}

// Icon Components with status-aware styling
function SparkIcon({ status }: { status: NodeStatus }) {
  return (
    <motion.div
      className="relative"
      animate={
        status === "active"
          ? {
              rotate: [0, 10, -10, 0],
            }
          : {}
      }
      transition={{ duration: 0.5, repeat: status === "active" ? Infinity : 0 }}
    >
      <Sparkles
        className={`w-12 h-12 transition-colors duration-300 ${
          status === "idle"
            ? "text-muted-foreground"
            : status === "active"
              ? "text-neon-cyan"
              : "text-neon-cyan/70"
        }`}
      />
      {status === "active" && (
        <motion.div
          className="absolute inset-0 flex items-center justify-center"
          animate={{ scale: [1, 1.3, 1], opacity: [0.5, 0, 0.5] }}
          transition={{ duration: 1, repeat: Infinity }}
        >
          <Sparkles className="w-12 h-12 text-neon-cyan" />
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
            ? {
                rotateY: [0, 360],
              }
            : {}
        }
        transition={{ duration: 2, repeat: status === "active" ? Infinity : 0, ease: "linear" }}
        style={{ transformStyle: "preserve-3d" }}
      >
        <Shield
          className={`w-12 h-12 transition-colors duration-300 ${
            status === "idle"
              ? "text-muted-foreground"
              : status === "active"
                ? "text-neon-purple"
                : "text-neon-purple/70"
          }`}
        />
      </motion.div>
      {/* Inner spark */}
      <div className="absolute inset-0 flex items-center justify-center">
        <Sparkles
          className={`w-5 h-5 transition-colors duration-300 ${
            status === "idle" ? "text-muted-foreground/50" : "text-neon-cyan"
          }`}
        />
      </div>
      {/* Scanning laser effect */}
      {status === "active" && (
        <motion.div
          className="absolute inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-neon-purple to-transparent"
          animate={{ top: ["0%", "100%", "0%"] }}
          transition={{ duration: 1.5, repeat: Infinity }}
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
            <Users
              className="w-12 h-12 text-muted-foreground"
            />
          </motion.div>
        )}
        {(status === "active" || status === "complete") && (
          <motion.div
            key="team"
            initial={{ opacity: 0, scale: 0.5 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex items-end gap-1"
          >
            {[0, 1, 2].map((i) => (
              <motion.div
                key={i}
                initial={{ y: 20, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: i * 0.1 }}
              >
                <div
                  className={`w-6 h-8 rounded-t-full border-2 ${
                    status === "active"
                      ? "border-neon-emerald bg-neon-emerald/20"
                      : "border-neon-emerald/70 bg-neon-emerald/10"
                  }`}
                  style={{
                    transform: i === 1 ? "scale(1.2)" : "scale(0.9)",
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
          className="absolute inset-0 rounded-lg overflow-hidden"
          style={{
            background:
              "repeating-linear-gradient(0deg, transparent, transparent 4px, rgba(52,211,153,0.1) 4px, rgba(52,211,153,0.1) 5px)",
          }}
          animate={{ y: [0, -5] }}
          transition={{ duration: 0.5, repeat: Infinity }}
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
            <FileCode className="w-12 h-12 text-muted-foreground" />
          </motion.div>
        )}
        {(status === "active" || status === "complete") && (
          <motion.div
            key="active"
            initial={{ opacity: 0, scale: 0.5 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex gap-1"
          >
            {[0, 1, 2].map((i) => (
              <motion.div
                key={i}
                initial={{ y: -20, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: i * 0.1 }}
              >
                <FileCode
                  className={`w-8 h-10 ${
                    status === "active" ? "text-neon-amber" : "text-neon-amber/70"
                  }`}
                />
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
      {/* Terminal cursor blink */}
      {status === "active" && (
        <motion.div
          className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-4 h-1 bg-neon-amber"
          animate={{ opacity: [1, 0, 1] }}
          transition={{ duration: 0.8, repeat: Infinity }}
        />
      )}
    </div>
  );
}
