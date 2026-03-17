# CODEBASE.md — Repository Map and Placement Rules

This file explains how the repository is structured, where major responsibilities live, how code should be located, and how to navigate safely before making changes.

Its purpose is to help the agent:
- find the right place to work quickly
- understand local architectural boundaries
- avoid duplicate logic and misplaced code
- extend the system in ways that remain coherent over time

This is the map of the codebase.

If `STACK.md` defines the technical world, this file defines the physical layout of that world.

If actual repository structure differs from older assumptions, actual repo reality wins.  
Update this file as the codebase evolves.

---

## Core Navigation Rule

Before writing code:

1. find the feature or subsystem you are touching
2. inspect the nearest existing implementation
3. inspect adjacent tests
4. inspect shared types/utilities used by that area
5. only then decide where the change belongs

Do not invent a location for new code until you have checked where related code already lives.

---

## Repository Intent

This repository should remain:
- easy to scan
- easy to extend
- easy to debug
- resistant to duplicate logic
- clear about ownership and boundaries

Prefer code placement that makes the system more legible for the next engineer.

The goal is not just to make things work.  
The goal is to make it obvious **where future work should go**.

---

## Placement Philosophy

Use these defaults unless the existing repo clearly follows a better established pattern:

- route-level code should stay thin
- domain logic should live near the domain, not buried in UI or transport layers
- shared utilities should be truly shared, not random overflow
- cross-cutting concerns should be explicit
- tests should live near or clearly map to the code they verify
- configuration should be centralized and discoverable
- generated code should be isolated from hand-written code

Prefer strong boundaries over convenience sprawl.

---

## Navigation Priorities

When trying to understand a feature, inspect in this order:

1. entry point
2. feature module
3. domain/service logic
4. data access layer
5. shared types/utilities
6. tests
7. config/environment shaping behavior
8. docs/specs/decision records if needed

Start at the edge the user experiences.  
Then walk inward to where the real logic lives.

---

## Canonical Top-Level Layout

This section defines the preferred meaning of common top-level folders.  
Follow actual repo truth if already established.

### Application / interface layer
- `app/` — route entrypoints, pages, layouts, route handlers
- `src/app/` — same purpose if repo uses `src/`
- `pages/` — legacy route layer if older framework structure exists

### Reusable UI
- `components/` — shared UI components used by multiple features
- `src/components/` — same if repo uses `src/`

### Feature / domain code
- `features/` — feature-scoped modules, workflows, state, UI, actions, logic
- `src/features/` — same if repo uses `src/`

### Shared code
- `lib/` — shared helpers, integrations, utilities, framework glue
- `src/lib/` — same if repo uses `src/`

### Backend/domain services
- `server/` — server-only logic, services, actions, domain workflows, infrastructure adapters
- `src/server/` — same if repo uses `src/`

### Database layer
- `db/` — schema, migrations, seed scripts, database helpers
- `prisma/` — Prisma schema, migrations, generated client conventions if used

### Tests
- `tests/` — integration/e2e/system tests
- `__tests__/` — local unit/integration tests where that pattern is already used

### Static assets
- `public/` — static assets served directly

### Documentation
- `docs/` — architecture notes, specs, runbooks, ADRs, supporting docs

### Scripts / automation
- `scripts/` — one-off or reusable automation scripts
- `bin/` — CLI-style repo utilities if used

### Configuration
- root config files or `config/` — app/runtime/tooling configuration
- `.github/` — CI, workflow automation, repo health

---

## Preferred Architectural Shape

The codebase should generally separate into these layers:

### 1. Interface layer
Handles:
- routes
- pages
- controllers/handlers
- request/response mapping
- UI rendering
- user interaction wiring

Should be:
- thin
- compositional
- free of deep business logic

### 2. Feature layer
Handles:
- user-facing flows
- feature-specific orchestration
- feature UI
- feature actions/use-cases
- feature-local validation and state

Should be:
- cohesive
- understandable in isolation
- the main home for non-trivial product behavior

### 3. Domain/service layer
Handles:
- business rules
- domain workflows
- cross-feature logic
- side-effect orchestration
- permissions and policy enforcement where appropriate

Should be:
- testable
- reusable
- not tied tightly to route/UI code
