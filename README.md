# Dragon World — AI World Engine v0.1

An AI-native persistent open-world prototype where players can freely define identities and actions while the world remains grounded by persistent state and rules.

## Project Overview

Dragon World explores how an open world can accept free-form player imagination without giving an LLM unconditional authority over world facts. Dragon Isles is the current vertical demo.

Players can define an identity, enter natural-language actions, inspect a structured preview, and explicitly confirm safe supported mutations through the Web UI. The world remains coherent through Persistent World State, World Rules, Grounding, JSON Schema Validation, server-side revalidation, and controlled State Mutation.

**Dragon World Web Interaction v0.1 is complete and frozen as a stable baseline.**

## Core Principles

- **Free Intent, Grounded Consequence.** Players may express or attempt anything; interpretation never guarantees success.
- **Never punish imagination; ground consequences.** Unsupported ideas remain expressible without silently becoming world facts.
- **World State is the source of truth.** The LLM proposes; deterministic code and schemas validate.
- **Only validated mutations become persistent world facts.** Preview is read-only, and Commit requires explicit human confirmation.
- **Stable Rules, Expandable World.** World Rules remain stable while the registered entities are not treated as the world's permanent boundary.
- **Unknown does not mean illegal.** Setting-compatible unknown exploration requires resolution instead of automatic rejection.
- **No silent generation.** Unknown Locations or NPCs are not created or persisted before a dedicated expansion system exists.

## Current Architecture

```text
Player
  ↓
Next.js Frontend
  ↓
FastAPI
  ↓
Action Interpreter
  ↓
World Validator
  ↓
Action Executor
  ↓
Persistent World State
```

The browser sends only the player's original natural-language input. Preview runs the structured pipeline without mutation. Confirm sends the original previewed input again, after which the server reloads current state, reruns validation, checks the mutation allowlist, and atomically commits an eligible change.

## Current Progress

- Step 1 — World State / World Rules ✅
- Step 2 — Player Schema & Grounding ✅
- Step 3 — Player Creation Interpreter ✅
- Step 4 — Persistent World State & Player Commit ✅
- Step 5.1 — Natural Language Action Interpreter ✅
- Step 5.2 — World Validation ✅
- Step 5.3 — Safe Action Execution ✅
- Step 5.4 — Web Interaction v0.1 ✅ **FROZEN**

## Completed Web Interaction Capabilities

- Persistent World State visualization
- Simplified Chinese Web UI
- Natural-language action input
- Structured Action Interpretation, Validation, and Execution Preview
- Human-in-the-loop confirmation and cancellation
- Server-side revalidation before Commit
- Safe atomic Persistent State updates within the mutation allowlist
- World State refresh after Commit
- Deterministic World Log and Developer View
- Blocked, conditional, clarification, and no-mutation handling
- Stale Preview and duplicate Commit protection
- Backend-offline handling
- Unknown open-world exploration baseline without silent entity generation

## Evaluation

- Player Creation Evaluation: **6/6 PASS**
- Action Interpretation Evaluation: **8/8 PASS**
- World Validation Evaluation: **9/9 PASS**
- Action Execution Evaluation: **8/8 PASS**
- Open World Exploration Regression: **PASS**
- Frontend TypeScript, ESLint, and Production Build: **PASS**

AI-facing features follow failure analysis, a focused Regression Case, Targeted Regression, and Full Regression. A frozen module is changed only after a reproducible real failure.

## Current Boundaries

The frozen v0.1 does **not** yet implement Generic NPC Runtime, NPC Dialogue, NPC Memory, Relationships, NPC Knowledge or Perception, Dynamic NPC Generation, Dynamic World Expansion, multi-step execution planning, narrator responses, quests, dynamic events, combat, Dragon Bonding Runtime, or a multimodal/3D world.

`requires_further_resolution` is the extension point for future entity resolution and controlled world expansion. It does not currently create a Location, NPC, event, or State Mutation.

## Project Structure

```text
api/        FastAPI bridge and public Web endpoints
core/       Shared Action Pipeline orchestration
data/       World seed, evaluation cases, and ignored local runtime saves
docs/       Architecture notes, safety boundaries, and frozen baselines
frontend/   Next.js Web UI, API client, and TypeScript contracts
llm/        Lightweight provider-neutral LLM client layer
prompts/    Grounding, interpretation, and validation system prompts
schemas/    JSON Schemas for strict structured outputs
scripts/    Save, creation, interpretation, validation, and execution CLIs
tests/      Deterministic local tests
```

## Quick Start

Python 3.10 or later and a current Node.js runtime are recommended.

### 1. Configure Python

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set `ARK_API_KEY` locally. Never commit `.env`.

### 2. Initialize a world and create a Player

```powershell
python scripts/init_save.py
python scripts/create_player.py
```

### 3. Start the FastAPI bridge

```powershell
python -m uvicorn api.app:app --reload
```

The API is available at `http://127.0.0.1:8000`, with interactive documentation at `/docs`.

### 4. Start the Web UI

```powershell
Set-Location frontend
Copy-Item .env.local.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`.

## Technology

- Python and FastAPI
- Next.js, React, and TypeScript
- JSON Schema and Structured Outputs
- Doubao / Volcengine Ark through an OpenAI-compatible SDK
- JSON Persistent State with atomic file replacement

## Roadmap

- Controlled World Resolution and Dynamic World Expansion
- Generic NPC Agent, Dialogue, Memory, Knowledge, and Relationships
- Multi-step Action Planning and additional safe Executor capabilities
- Narrator / diegetic world responses
- Quest, Dynamic Event, Combat, and Dragon Bonding systems
- Future multimodal and 3D first-person experiences

Roadmap items are planned work and are not part of the frozen v0.1 implementation.
