Here is the exact, copy-pasteable PRD to feed into your deepthink AI to build the "Spec Slicer" architecture.

PRD: The "Spec Slicer" Context Injector Upgrade
1. Executive Summary
Objective: Resolve token-limit exhaustion, attention degradation, and wasted API costs in the Flowmind IDE's parallel execution swarm.
Current State: The entire Product Requirements Document (PRD) is passed to every parallel worker in the Executor Station, maxing out context windows and causing the LLM to hallucinate or lose focus on its specific task.
Target State: The Python backend acts as a "Context Injector." It parses the raw markdown PRD, slices it by headers, and only feeds the explicitly required sections to each individual worker based on the Planner's routing schema.

2. System Architecture Updates
2.1 The Planner Station (Schema Upgrade)
The Planner Agent's system prompt and JSON output schema must be updated to map specific files to specific sections of the PRD.

Input: The full PRD markdown file.

Action Required: Update the execute_live_swarm logic for the Planner to enforce this new JSON schema constraint.

New JSON Schema:

JSON
{
  "architecture_summary": "string",
  "project_dependencies": ["string"],
  "file_tree": [
    {
      "filepath": "string",
      "purpose": "string",
      "complexity": "low" | "medium" | "high",
      "required_spec_sections": ["string"] 
    }
  ]
}
(Note for AI: required_spec_sections must exactly match the literal text of the Markdown headers found in the PRD, e.g., "3.1 Color Palette", "4.2 Node Lifecycle".)

2.2 The Python Spec Slicer (Backend Utility)
A new utility class or function must be added to the FastAPI backend to handle markdown extraction without requiring an LLM call.

File: backend/utils.py (or within the existing FileSystemManager).

Function Signature: def extract_markdown_sections(markdown_text: str, target_headers: list[str]) -> str:

Logic:

Parse the provided markdown_text.

Locate the headers provided in the target_headers list (matching ## or ### levels).

Extract the content directly beneath those headers until the next header of equal or higher weight.

Concatenate and return the extracted blocks as a single string.

Edge Case: If a requested header is not found, log a warning but continue executing the remaining targets.

2.3 The Executor Station (Prompt Assembly)
The generate_file_content method must be updated to dynamically assemble the prompt using the sliced context.

Current Behavior: Sends the full PRD.

New Behavior:

Read the master spec.md from the workspace_sandbox.

Call extract_markdown_sections() using the required_spec_sections array provided by the Planner for the current file.

Construct the prompt payload.

Prompt Template:

Plaintext
You are an expert developer building a single file for a larger system.
Filepath: {filepath}
Architecture Summary: {architecture_summary}
Purpose of this file: {purpose}

Here are the specific technical requirements extracted from the master PRD that apply to your file:
<extracted_specs>
{sliced_markdown_content}
</extracted_specs>

Write the complete code for this file. DO NOT output markdown formatting blocks (like ```python), explanations, or pleasantries. Output ONLY the raw, functional code.
3. Execution Sequence & Data Flow
Spec Factory writes spec.md to disk.

Planner reads spec.md and returns JSON with the mapped required_spec_sections for each file.

Commander iterates through the file_tree array and launches async tasks via asyncio.gather().

Executor Tasks (running in parallel) use the Spec Slicer to grab their specific chunks of spec.md.

OpenRouter API is called with the highly compressed, surgical prompts.

Files are written to disk via FileSystemManager.

4. Constraints & Guardrails
Do not use an LLM for extraction: The markdown parsing must be done natively in Python using regex or string manipulation to guarantee speed and zero token cost.

Keep existing WebSockets intact: The UI broadcast events (station_update, monaco_update) must not be altered during this backend refactor.

When you hand this PRD and your repomix.xml over to your deepthink model, it will know exactly how to write the regex parser and update your FastAPI routes.

Once it generates the backend code and you drop it into your local files, your token usage is going to plummet while the accuracy of your parallel agents skyrockets.