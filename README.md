# Dragon World — AI World Engine v0.1

An AI-native persistent open-world prototype where players can freely define identities and actions while the world remains grounded by persistent state and rules.

## Project Overview

Dragon World explores how an open world can accept free-form player imagination without giving an LLM unconditional authority over world facts. Dragon Isles is the current vertical demo.

Players can:

- Define their own identity in natural language.
- Describe actions without being restricted to traditional menu options.
- Express unusual ideas and attempt actions beyond a fixed verb list.

The world remains coherent through:

- Persistent World State
- World Rules
- Grounding
- JSON Schema Validation
- Controlled State Mutation

The current implementation supports grounded Player Creation, persistent Player Commit, and read-only Action Interpretation previews. It does not yet execute runtime actions or make NPC decisions.

## Core Principles

- **Free Intent, Grounded Consequence.**
- **Never punish imagination; ground consequences.**
- **World State is the source of truth.**
- **LLM proposes; system validates.**
- **Only validated mutations become persistent world facts.**

Player expression, intent, and objective World Facts are deliberately separated. A player can say or attempt anything, but an unsupported statement does not automatically rewrite the world.

## Current Architecture

```text
Natural Language
→ Interpreter
→ Structured Output
→ Schema Validation
→ Grounding / Validation
→ Preview
→ Commit
→ Persistent World State
```

Player Creation currently follows the complete preview-and-confirmation flow before committing only Player State to the active save. Step 5.1 Action Interpreter currently stops at Preview. Step 5.2 World Validation has not started, so interpreted actions are never executed or persisted.

## Current Progress

- Step 1 — World State / World Rules ✅
- Step 2 — Player Schema & Grounding ✅
- Step 3 — Player Creation Interpreter ✅
- Step 4 — Persistent World State & Player Commit ✅
- Step 5.1 — Natural Language Action Interpreter ✅
- Step 5.2 — World Validation 🚧

## Evaluation

- Player Creation Evaluation: **6/6 PASS**
- Action Interpretation Evaluation: **8/8 PASS**

AI-facing features are developed with failure analysis, targeted regression, and full regression. A real failure first becomes a focused regression case; the fix is verified against that case and then against the complete baseline to avoid breaking previously valid behavior.

## Project Structure

```text
data/       World seed, evaluation cases, and ignored local runtime saves
schemas/    JSON Schemas for strict structured model outputs
prompts/    Grounding and interpretation system prompts
scripts/    Save, Player Creation, Commit, and Action Interpreter CLIs
llm/        Lightweight provider-neutral LLM client layer
tests/      Local deterministic tests that do not require an LLM call
docs/       Architecture notes, design principles, and frozen baselines
```

## Quick Start

Python 3.10 or later is recommended.

### 1. Create and activate a virtual environment

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS or Linux:

```bash
source .venv/bin/activate
```

### 2. Install the minimal dependencies

```bash
python -m pip install -r requirements.txt
```

### 3. Create local provider configuration

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS or Linux:

```bash
cp .env.example .env
```

Edit the local `.env` file and set:

```dotenv
ARK_API_KEY=<your_volcengine_ark_api_key>
```

Never commit `.env`. The repository-safe `.env.example` contains only empty or non-secret example values.

### 4. Initialize a new persistent save

```bash
python scripts/init_save.py
```

### 5. Create, preview, and confirm a Player

```bash
python scripts/create_player.py
```

The Player is written to `data/saves/current_world.json` only after Schema Validation, Grounding, and explicit confirmation.

### 6. Preview a natural-language action

```bash
python scripts/interpret_action.py
```

Action Interpretation is read-only in Step 5.1. It produces Structured Action Intent but does not execute the action or mutate the save.

## Technology

- Python
- JSON Schema
- Structured Outputs
- Doubao / Volcengine Ark
- OpenAI-compatible Python SDK
- JSON Persistent State

## Roadmap

- World Validation
- Action Execution
- NPC Agent
- NPC Memory
- Dynamic Events
- Web UI
- Future multimodal and first-person dragon-riding experience

Roadmap items are planned work and are not part of the current v0.1 implementation.
