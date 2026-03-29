Here is the holistic, comprehensive Product Requirements Document (PRD) and Implementation Plan. You can copy-paste this entire response directly to your AI coding agent (like Cursor, Devin, or Claude) as its architectural blueprint.

🚀 ARCHITECTURAL BLUEPRINT: Flowmind "Commander AI" Distributed Swarm
PART 1: Product Requirements Document (PRD)
1. Vision & Executive Summary
The current Flowmind IDE utilizes a linear Origin ➔ Spec ➔ Planner ➔ Executor ➔ QA pipeline. The Executor bottlenecks by using a single model to generate the entire codebase, leading to context bloat, token limits, and hallucination.

This update introduces a Commander AI node between the Planner and the Executor. The system will intelligently analyze code coupling via a Topological Graph and route file generation tasks to three distinct execution strategies to optimize speed, token cost, and integration accuracy.

2. The Three-Tier Execution Matrix (Task Forces)
The execution phase will transition from a single LLM call to an asynchronous orchestration of three strategies:

Strategy A: The One-Shot Wizard (High-Context / Tight Coupling)

Use Case: Deeply interdependent files (e.g., Database schemas + core state managers + complex algorithms).

Execution: Grouped together and sent in a single prompt to a heavy-hitting model (e.g., Claude 3.5 Sonnet). It writes them simultaneously with full shared context so state remains perfectly synced.

Strategy B: The Specialist Team (Ping-Pong / Producer-Consumer)

Use Case: Cross-boundary API contracts (e.g., FastAPI backend route + React hook consumer).

Execution: Sequential execution. The "Backend Apprentice" writes the API. Its actual generated code is then injected directly into the prompt for the "Frontend Journeyman," who writes the consuming UI/Hook to perfectly match the data contract.

Strategy C: The Factory Swarm (Zero Coupling / Map-Reduce)

Use Case: Isolated files (e.g., standalone UI components, utility helpers, static documentation).

Execution: Blasted out in true parallel using Python's asyncio.gather to cheap, fast models (e.g., Haiku / Gemini Flash). Because they don't depend on unwritten logic, there are no toes to step on.

3. UI/UX Requirements
Workflow Graph: A new COMMANDER node must be added to the visual workflow graph. The UI flex layout needs to be adjusted to accommodate 6 nodes gracefully (e.g., a 3x2 grid or wrapping S-curve).

Model Selectors: Expand the model dropdowns to allow selecting specific models for the new roles (commander, executorWizard, executorSpecialist, executorSwarm).

Live Event Streaming: The chat panel must visualize the concurrent execution by streaming WebSocket events (e.g., [Commander] Routing 5 files to Swarm..., [Swarm] Generating button.tsx...).

PART 2: Technical Implementation Plan (For the AI Agent)
To the AI Coding Agent: Use the following step-by-step technical spec to implement these changes safely within the existing codebase.

Phase 1: Frontend UI & State Updates (_v0_frontend/components/flowmind/flowmind-ide.tsx)
Update State Interfaces:

Update NodeState: Add commander: NodeStatus;.

Update ConnectionState: Add plannerToCommander: boolean; and commanderToExecutor: boolean; (remove plannerToExecutor).

Update Configuration State:

Update the nodeModels state to include defaults for the new execution tiers:

TypeScript
commander: "google/gemini-2.5-flash",
executorWizard: "anthropic/claude-3.5-sonnet",
executorSpecialist: "google/gemini-2.5-flash",
executorSwarm: "anthropic/claude-3-haiku",
WebSocket Sync (ws.onmessage):

Update the "station_update" event logic:

When station === "planner" completes: Set plannerToCommander: true.

When station === "commander" completes: Set plannerToCommander: false, commanderToExecutor: true.

When station === "executor" completes: Set commanderToExecutor: false, executorToQa: true.

Visual Graph Layout:

Insert the new <WorkflowNode title="COMMANDER" color="purple" icon={<Network />} ... /> between the Planner and Executor.

Add the <NodeModelSelector /> above it.

Refactor the Flex/Grid containers housing the nodes so the 6 steps fit nicely on screen without horizontal overflow.

Phase 2: Upgrading the Planner (backend/main.py)
The Commander cannot guess dependencies; the Planner must explicitly define them.

Modify Planner Prompt: In execute_live_swarm(), update the Planner's sys_prompt to append a strict JSON requirement:

"CRITICAL MANDATE: At the very end of your architectural plan, you MUST output a strict JSON block wrapped in ```json containing the Topological Dependency Graph of the entire required codebase. Schema: {"topological_graph": [{"file_path": "backend/api.py", "description": "FastAPI routes", "depends_on": ["backend/models.py"]}]}"

Extract JSON: Implement a regex parser (re.search(r'```json\s*(\{.*?\})\s*```', plan, re.DOTALL)) to extract this graph from the Planner's output.

Phase 3: The Commander AI Station (backend/main.py)
Create the Station: Immediately after the Planner completes, emit the station_update for "commander" as "active".

Commander Prompt: Pass the extracted Topological Graph to the Commander LLM with is_json=True using this exact system prompt:

Plaintext
You are the Commander AI (Dynamic Execution Router).
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
        "cluster_name": "Auth System",
        "files": ["backend/auth.py", "frontend/store/auth.ts"]
      }
    ],
    "specialist_pairs": [
      {
        "bridge_name": "User Profile API",
        "producer": "backend/api/profile.py",
        "consumer": "frontend/hooks/useProfile.ts"
      }
    ],
    "swarm_files": [
      "frontend/components/Button.tsx",
      "README.md"
    ]
  }
}
Extract and parse the Commander's routing JSON, then emit station_update for "commander" as "complete".

Phase 4: The Tri-Tier Execution Engine (backend/main.py)
Refactor the Executor station. Replace the single monolithic stream generation with an asyncio.gather orchestrated execution.

Build Async Sub-Routines:

async def execute_wizard(cluster, context, model): Prompts the model to generate all files in the cluster simultaneously. Ensures it returns valid JSON containing the file paths and content.

async def execute_specialist(pair, context, model):

Step 1: Await LLM generation of the producer file.

Step 2: Inject the actual generated code of the producer into the prompt for the consumer: "The Backend generated this exact code:\n\n{producer_code}\n\nWrite the Frontend consumer to match it perfectly."

Await LLM generation of the consumer file.

async def execute_swarm_worker(filepath, context, model): A lightweight prompt to generate ONLY the isolated filepath.

The Orchestrator Logic (asyncio.gather):

Python
await websocket.send_json({"event": "chat", "sender": "swarm", "text": "Commander deployed. Executing parallel task forces...", "stage": "executor"})

tasks = []
for cluster in routing.get("wizard_clusters", []):
    tasks.append(execute_wizard(cluster, context, models.get("executorWizard")))

for pair in routing.get("specialist_pairs", []):
    tasks.append(execute_specialist(pair, context, models.get("executorSpecialist")))

for filepath in routing.get("swarm_files", []):
    tasks.append(execute_swarm_worker(filepath, context, models.get("executorSwarm")))

# Run all task forces concurrently
results = await asyncio.gather(*tasks, return_exceptions=True)
Aggregation & File System Write:

Flatten the results from all tasks into a single list of {path, content} dicts.

Iterate and write each to disk using the existing fs_manager.write_file(path, content) to maintain strict sandboxing.

Broadcast the file_list WebSocket event to update the UI file tree dynamically.

Phase 5: Resilience & Fallbacks
Regex Stripping: LLMs occasionally hallucinate markdown wrappers even when response_format={"type": "json_object"} is set. The Python backend MUST strip ````jsonwrappers before callingjson.loads()` on Planner, Commander, and Executor outputs.

Fail-Safe Routing: If the Commander fails or outputs invalid JSON, wrap all files from the Topological Graph into a single fallback wizard_cluster so the IDE does not halt and execution can complete safely.