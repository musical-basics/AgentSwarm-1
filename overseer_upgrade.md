🚀 ARCHITECTURAL BLUEPRINT: The "Overseer" Iterative Swarm Engine
PART 1: Product Requirements Document (PRD)
1. Vision & Executive Summary
Objective: Resolve token-limit exhaustion, prevent context degradation, and force the Commander AI to utilize parallel Swarm task forces instead of defaulting everything to a single One-Shot Wizard.

Current Problem: The Spec Factory hands a massive, monolithic PRD directly to the Planner. The Planner generates a massive dependency graph. When the Commander analyzes this huge, highly-coupled graph, it panics and routes almost everything to the "One-Shot Wizard" to avoid integration errors. This burns through 4k/8k+ context windows instantly, increases API costs, and defeats the purpose of the parallel swarm.

Target State: Introduce an Overseer AI (The Agile Product Manager) situated between the Spec Factory and the Planner. The Overseer reads the monolithic PRD once and slices it into sequential "Implementation Chunks" (e.g., 1. Database & Config, 2. Backend Routes, 3. Frontend UI). The swarm then processes one chunk at a time in an iterative loop (Planner ➔ Commander ➔ Executor ➔ QA).

2. System Architecture Updates
2.1 The Overseer Station (New Node)
Location: Between the Spec Factory and the Planner.

Role: Analyzes the full PRD and outputs a strict JSON roadmap of isolated epics/chunks.

Output Schema:

JSON
{
  "chunks": [
    {
      "chunk_id": 1,
      "title": "Database and Core Models",
      "description": "Setup SQLAlchemy models and DB connections. Ignore APIs and UI.",
      "relevant_spec_sections": ["Data Architecture", "Schema"]
    },
    {
      "chunk_id": 2,
      "title": "Backend API",
      "description": "Build FastAPI routes to expose the models."
    }
  ]
}
2.2 The Iterative Execution Loop
The linear pipeline is refactored into an async for-loop in the Python backend.

Initialization: Origin ➔ Spec Factory ➔ Overseer.

Execution Loop (For each chunk):

Overseer hands the current Chunk to the Planner.

Planner creates an architecture plan and a tiny Topological Graph for only the files needed in this chunk.

Commander analyzes the tiny graph. Because it's bite-sized with low coupling, the Commander confidently routes tasks to the Swarm and Specialist models, naturally bypassing the Wizard bottleneck.

Executor parallel-generates the files.

QA reviews the chunk.

System broadcasts a loop reset. Proceed to the next chunk.

2.3 Context Compression Guardrails
To prevent token bloat during the loop, the Planner and Executor will no longer receive the full PRD. They will receive:

The description and requirements for the current chunk.

A flat stringified tree of existing_files in the workspace, so they know what has already been built by previous chunks and can confidently import from them without overwriting or hallucinating dependencies.

3. UI/UX Requirements
Workflow Graph Expansion: Add a new OVERSEER node to the React UI graph, situated between Spec Factory and Planner.

Loop Visualization: When a chunk completes and loops back, the backend must broadcast WebSocket events to set the downstream nodes (Planner, Commander, Executor, QA) back to "idle" so the UI visually resets and lights up iteratively for the new chunk.

Chat Panel Streaming: Broadcast the current chunk status to the user (e.g., "🔄 [Overseer] Starting Chunk 1 of 3: Database and Core Models...").

Model Selector: Add an Overseer model dropdown so the user can select the routing model.

PART 2: Technical Implementation Plan (For the AI Agent)
To the AI Coding Agent: Use the following step-by-step technical spec to implement the Overseer architecture safely within the existing codebase.

Phase 1: Frontend UI & State Updates (_v0_frontend/components/flowmind/flowmind-ide.tsx)
1. Update State Interfaces:

NodeState: Add overseer: NodeStatus;.

ConnectionState: Replace specToPlanner with specToOverseer: boolean; and overseerToPlanner: boolean;.

2. Update Configuration State:

Add overseer: "google/gemini-2.5-flash" to the nodeModels initial state.

3. WebSocket Event Handling (ws.onmessage):

Update the station_update logic:

When specFactory completes ➔ set specToOverseer: true.

When overseer completes ➔ set specToOverseer: false, overseerToPlanner: true.

When planner completes ➔ set overseerToPlanner: false, plannerToCommander: true.

Add a new event listener for "chunk_start":

When "chunk_start" is received, reset planner, commander, executor, and qaReviewer to "idle" in NodeState.

Reset their connection states (like plannerToCommander, commanderToExecutor, executorToQa) to false.

Set overseerToPlanner: true to kick off the visual flow again for the new chunk.

4. Visual Graph Layout:

Insert the <WorkflowNode title="OVERSEER" color="indigo" icon={<Eye />} ... /> into the UI between Spec Factory and Planner. (Note: Import Eye from lucide-react).

Adjust the Flexbox/Grid layout (e.g., reorganizing the flex containers for the Middle Row) to accommodate 7 nodes seamlessly so they don't overflow horizontally.

Phase 2: Building the Overseer Station Backend (backend/main.py)
1. The Overseer Execution:
Inside _execute_live_swarm_logic, insert the Overseer logic immediately after the Spec Factory finishes emitting its station_update.

System Prompt:

Plaintext
You are the Overseer AI (Agile Product Manager).
Your job is to read the full Product Requirements Document (PRD) and break it down into sequential, manageable "Implementation Chunks" (Sprints).
Rule 1: Chunks MUST be strictly sequential. (e.g., Chunk 1: Database/Config. Chunk 2: Backend APIs. Chunk 3: Frontend UI).
Rule 2: Output strictly valid JSON.

Schema:
{
  "chunks": [
    {
      "chunk_id": 1,
      "title": "Core Data Models",
      "description": "Extracted specifications from the PRD relevant ONLY to this chunk. Be highly detailed."
    }
  ]
}
Extraction & Artifact: Call the LLM with is_json=True. Extract the JSON, strip markdown wrappers (````json``), parse it into a Python dict, and save it as an artifact (2_overseer_chunks.json). Emit station_update for overseer as complete.

Phase 3: The Iterative Execution Loop (backend/main.py)
1. Refactor into an async for Loop:
Wrap the Planner (Station 3), Commander (Station 3.5), Executor (Station 4), and QA (Station 4.5) logic inside an asynchronous loop over the extracted chunks:

Python
chunks = overseer_data.get("chunks", [])
total_chunks = len(chunks)

for index, chunk in enumerate(chunks):
    chunk_num = index + 1
    chunk_title = chunk.get("title", f"Chunk {chunk_num}")
    chunk_desc = chunk.get("description", "")
    
    # 1. Reset downstream UI for the new chunk
    await safe_send(websocket, {"event": "chunk_start", "chunk_title": chunk_title})
    
    # 2. Broadcast to Chat
    await safe_send(websocket, {
        "event": "chat", 
        "sender": "swarm", 
        "text": f"🔄 **[Overseer] Releasing Chunk {chunk_num}/{total_chunks}: {chunk_title}**\nFocus: {chunk_desc}", 
        "stage": "overseer"
    })

    # --- PLANNER STATION LOGIC HERE ---
    # --- COMMANDER STATION LOGIC HERE ---
    # --- EXECUTOR STATION LOGIC HERE ---
    # --- QA STATION LOGIC HERE ---

    New Step: The Ledger Update (Post-QA)

After the QA Station finishes a chunk, the backend must read the actual code generated in that chunk.

Pass that code to a lightweight summarization prompt (e.g., using Haiku or Flash).

Prompt: "Extract the strict API contracts, database schemas, and global state shapes from this code. Do not summarize the logic; only summarize the interfaces."

Append this output to a rolling global_architecture_ledger.md file saved in the workspace.

Then, update Phase 4.3 (Update Executor Input):
Instead of just sending the existing_files_str, you must send the existing_files_str AND the contents of the global_architecture_ledger.md.

Phase 4: Context Compression & Prompt Updates
Because execution is now chunked, the Planner and Executor must understand what has already been built so they don't hallucinate or overwrite files unnecessarily.

1. Dynamic Workspace Context:
Inside the loop, dynamically read the current file tree before the Planner executes. Move the existing flatten_files helper up, and generate:

Python
existing_files_str = "\n".join(flatten_files(fs_manager.list_files()))
2. Update Planner Input:

Old behavior: Passed the entire spec (PRD) as user_prompt.

New behavior:

System Prompt Addition: "You are planning architecture for CHUNK {chunk_num} of {total_chunks}. Create a Topological Dependency Graph ONLY for the new files required in THIS chunk. Do not replan existing files."

User Prompt Payload: Send the chunk_desc and the existing_files_str (plus a brief PRD summary if needed).

3. Update Executor Input:

Modify the shared_context variable generated before the Executor sub-routines. It should now only contain:

The chunk_desc.

The Planner's output for this specific chunk.

The current file tree (existing_files_str).
Do not include the master PRD.

4. Artifact Naming Resilience:
Because files are generated in loops, update artifact saving inside the loop to include the chunk ID to prevent overwriting:

fs_manager.write_file(f"{artifact_dir}/3_plan_chunk_{chunk_num}.md", plan)

fs_manager.write_file(f"{artifact_dir}/3b_commander_routing_chunk_{chunk_num}.json", json.dumps(routing, indent=2))

fs_manager.write_file(f"{artifact_dir}/4_executor_raw_chunk_{chunk_num}.json", ...)

fs_manager.write_file(f"{artifact_dir}/5_qa_review_chunk_{chunk_num}.md", ...)

Phase 5: Resilience Guardrails
JSON Stripping: Ensure ````json` stripping safeguards are applied to the Overseer's output, exactly as they currently are for the Planner and Commander.

Fallback Roadmap: If the Overseer fails to generate valid JSON, fall back to a 1-chunk array containing the entire project so execution does not crash.

Cost Tracking: When calling update_run_costs, append the chunk number to the stage name (e.g., f"3_planner_chunk_{chunk_num}") so costs are properly separated per chunk.

Workflow Completion: Ensure the DevOps Runner commands generation and await safe_send(websocket, {"event": "workflow_complete"}) are only executed after the async for loop has entirely finished.