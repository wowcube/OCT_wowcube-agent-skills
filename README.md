# 🧊 WowCube AI Agent Skills Repository

Welcome to the official AI Agent skill set and knowledge base for WowCube game development. This repository is designed to be ingested by LLM-powered coding agents (like Claude Code, Cursor, or GitHub Copilot) to ensure they write highly optimized, hardware-accurate C/C++ code for the WowCube platform.

## 📂 Repository Structure

* `agents.md` — **The Constitution.** Global mandates and strict C++ rules for the WowCube architecture.
* `docs/reference_examples.md` — **The API Encyclopedia.** Production-ready patterns for FSMs, memory pools, physics, and UI lookups.
* `templates/base_app.h` — **The Boilerplate.** A clean, FSM-driven starting point for any new project.
* `skills/` — **The Actionable Prompts.** Step-by-step instructions for agents to execute specific, complex tasks without hallucinating syntax.

## 🤖 How to Use This Repository with AI Agents

To get the best results from your AI agent, point it to this repository and ask it to use a specific skill. 

### Example Prompt for your Agent:

> "I am building a new WowCube game. Please read the core rules in `agents.md` and the API patterns in `docs/reference_examples.md` from this repository. 
> 
> Once you understand the architecture, use the skill `skills/01_scaffold_game_and_fsm/instructions.md` to initialize a new game called 'Space Miner' using the template in `templates/base_app.h`."

### Available Skills
1. fsm: Initializes a clean project with a Finite State Machine.
2. topology: Adds correct physical cube twist handling.
3. collisions: Adds hitboxes and interaction logic.
4. parallax: Integrates accelerometer data for gravity and parallax.


---
*Built to ensure no zero-index loops, no memory leaks, and perfect hardware twist synchronization.*
