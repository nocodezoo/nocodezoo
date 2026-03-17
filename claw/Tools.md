# TOOLS.md — Tooling Doctrine for a High-Performance Coding Agent

This file defines how to use tools effectively in this workspace.

Its purpose is to make the agent:
- fast without becoming reckless
- autonomous without becoming sloppy
- precise without becoming brittle
- capable of shipping real software, not just plausible code

Use tools to reduce uncertainty, accelerate execution, validate changes, and avoid preventable mistakes.

If a local file conflicts with generic assumptions, local repo truth wins.

---

## Core Tool Principles

### 1. Read before writing
Before editing code:
- locate the relevant files
- inspect adjacent implementations
- find existing patterns
- understand the architecture boundary you are touching
- read enough context to avoid introducing a foreign style or duplicate abstraction

Do not start coding from guesswork.

### 2. Search before asking
If relevant context likely exists in the repo:
- search for it
- inspect the nearest existing implementation
- check docs, configs, tests, and type definitions
- ask the user only when the missing information materially affects the outcome

Avoid asking questions the codebase can answer.

### 3. Use the smallest effective tool
Prefer the least invasive path that solves the task well.

Typical order:
1. search / navigate
2. read files
3. edit targeted files
4. run validation
5. use browser/runtime tools if needed
6. use external docs/web only when local context is insufficient or freshness matters

Do not jump to heavyweight actions without reason.

### 4. Make narrow, deliberate changes
Prefer:
- small diffs
- local fixes
- preserving surrounding conventions
- incremental validation

Avoid:
- unrelated refactors
- rewriting files for style alone
- introducing new patterns when existing ones are adequate
- changing architecture casually

### 5. Verify before claiming success
Do not call work done because the code “looks right.”

Validation should scale with risk:
- tiny text change: light verification
- local logic change: targeted checks
- feature work: lint, typecheck, relevant tests, build if affected
- auth, billing, migrations, infra, public APIs: stronger validation and more caution

### 6. Prefer existing capability over new dependencies
Before adding a dependency:
- check whether the repo already has a suitable tool/library
- check whether the standard library or framework already solves it
- check whether an existing local utility should be extended instead

New dependencies add long-tail maintenance cost.

### 7. Do not trust assumptions when tools can verify
If a tool can confirm:
- file existence
- command availability
- type correctness
- test behavior
- runtime errors
- route behavior
- build status

…use the tool instead of guessing.

---

## Environment Detection Rules

Always detect the local environment before acting. Do not assume the stack.

Inspect, in roughly this order where relevant:
- root files and repo structure
- lockfiles
- package manifests
- build configs
- test configs
- lint/typecheck configs
- CI config
- Docker / compose files
- task runners
- README / docs / runbooks

### Package / runtime detection

#### JavaScript / TypeScript
Detect package manager from lockfile:
- `pnpm-lock.yaml` → use `pnpm`
- `bun.lockb` or `bun.lock` → use `bun`
- `yarn.lock` → use `yarn`
- `package-lock.json` → use `npm`

Inspect:
- `package.json`
- `tsconfig.json`
- framework configs
- workspace configs (`turbo.json`, `nx.json`, monorepo manifests)

#### Python
Prefer the project’s existing toolchain:
- `uv.lock` / `pyproject.toml` with uv → use `uv`
- `poetry.lock` → use `poetry`
- `Pipfile` → use `pipenv`
- `requirements.txt` / `pyproject.toml` → follow local convention

Inspect:
- `pyproject.toml`
- test config
- formatter/linter config

#### Rust
Use:
- `cargo`
Inspect:
- `Cargo.toml`
- workspace members
- clippy / rustfmt configuration

#### Go
Use:
- `go`
Inspect:
- `go.mod`
- workspace layout
- lint/test scripts if present

#### Ruby
Use:
- `bundle`
Inspect:
- `Gemfile`
- test/lint configs

#### Java / Kotlin
Use the repo’s build tool:
- `./gradlew` if Gradle wrapper exists
- `mvnw` / `mvn` if Maven is used

#### .NET
Use:
- `dotnet`
Inspect:
- solution and project files
- test project structure

#### PHP
Use:
- `composer`
Inspect:
- framework and test tooling

#### Elixir
Use:
- `mix`

If multiple ecosystems exist, identify the relevant subproject before running commands.

---

## Tool Priority by Task

### Navigation / discovery
Use search and file inspection first to answer:
- where does this feature live?
- what is the nearest existing pattern?
- what files define the behavior?
- where are tests for this area?
- what commands validate this part of the system?

Search for:
- identifiers
- route names
- component names
- API handlers
- error strings
- config keys
- environment variables
- test names
- schema/table/model names

Do not open large numbers of files blindly.

### Reading files
Read only what is needed to do quality work.

Prefer this order:
1. directly relevant file
2. adjacent implementation
3. shared utility / abstraction
4. tests for the same area
5. config / types / schema
6. docs or ADRs if architectural intent matters

Start narrow, then widen only if needed.

### Editing files
When editing:
- preserve local conventions
- preserve intent
- keep names explicit
- avoid cosmetic churn
- update nearby tests/docs when the change affects behavior or usage

Prefer targeted edits over full-file rewrites unless a rewrite is clearly justified.

### Terminal / command execution
Use the terminal to:
- inspect scripts
-
