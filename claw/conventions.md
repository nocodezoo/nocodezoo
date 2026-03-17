# CONVENTIONS.md — Engineering Conventions and Quality Rules

This file defines the coding conventions, implementation preferences, and quality rules for this workspace.

Its purpose is to help the agent:
- write code that fits the repo
- make changes that are easy to maintain
- choose clarity over cleverness
- avoid recurring classes of low-quality implementation

These conventions are defaults unless the existing codebase clearly establishes a better local pattern.

If `STACK.md` defines the technical world and `CODEBASE.md` defines where code belongs, this file defines how code should look, behave, and evolve within that world.

---

## Core Standard

Write code that is:

- clear
- explicit
- maintainable
- locally understandable
- easy to change
- hard to misuse

Prefer code that a strong engineer can understand quickly over code that tries to impress.

The goal is not maximum cleverness.  
The goal is maximum long-term usefulness.

---

## Primary Principles

### 1. Clarity beats cleverness
Prefer:
- obvious control flow
- descriptive names
- straightforward data movement
- simple composition

Avoid:
- dense abstractions
- compressed one-liners that hide meaning
- “smart” patterns that save lines but increase cognitive load
- indirect code when direct code is good enough

### 2. Local reasoning matters
A file or function should be understandable without hunting across the entire repo.

Prefer:
- small focused modules
- explicit inputs and outputs
- visible dependencies
- logic close to its owning domain

Avoid:
- hidden side effects
- magical implicit behavior
- sprawling files with mixed responsibilities

### 3. Simplicity is a feature
Use the simplest design that fully solves the problem.

Do not:
- over-generalize early
- build abstractions before reuse is real
- introduce framework-like layers inside the app without need
- solve future imaginary scale at today’s cost

### 4. Correctness before polish
Pretty code that behaves incorrectly is bad code.

Prioritize:
- correctness
- good boundaries
- type safety
- meaningful validation
- testability

Then improve elegance.

### 5. Consistency compounds
In a team or long-lived repo, consistency beats isolated brilliance.

Follow:
- existing naming patterns
- existing file structure
- existing architectural style
- existing error and validation patterns

Improve local consistency before introducing new style ideas.

---

## Naming Conventions

Names should reveal:
- what something is
- what it owns
- what it returns
- how broadly it is meant to be used

### Prefer names that are:
- explicit
- specific
- stable
- domain-oriented

### Good examples
- `createInvoice`
- `getWorkspaceMembers`
- `validateCheckoutInput`
- `BillingSummaryCard`
- `useEditorSelection`
- `syncCustomerRecords`

### Avoid names like:
- `handleData`
- `processThing`
- `doStuff`
- `temp`
- `misc`
- `common`
- `manager`
- `helper`

If a name could mean many things, it probably means nothing.

### Boolean naming
Boolean values should read clearly as true/false.

Prefer:
- `isLoading`
- `hasAccess`
- `canEdit`
- `shouldRetry`

Avoid:
- `loading`
- `access`
- `editFlag`

### Collection naming
Collections should be plural.

Prefer:
- `users`
- `invoices`
- `workspaceMembers`

### Singular naming
Single entities should be singular.

Prefer:
- `user`
- `invoice`
- `workspaceMember`

### Function naming
Use verbs for actions, nouns for values.

Prefer:
- `createOrder`
- `fetchProjects`
- `normalizePayload`
- `buildSearchQuery`

Avoid:
- `orderData`
- `projectThing`

---

## File Naming

File names should communicate domain and responsibility.

### Prefer
- `create-invoice.ts`
- `invoice-schema.ts`
- `billing-summary-card.tsx`
- `use-editor-shortcuts.ts`
- `workspace-member-list.tsx`

### Avoid
- `utils.ts`
- `helpers.ts`
- `common.ts`
- `misc.ts`
- `index2.ts`
- `new.ts`

### File naming style
Use the repo’s established convention. If no convention exists:
- prefer `kebab-case` for files in TS/JS projects
- keep component names aligned with exported symbols where helpful

### `index` files
Use `index.ts` only when it improves import ergonomics and does not hide ownership.

Do not overuse barrel exports in ways that:
- blur boundaries
- create circular dependencies
- make search/navigation harder

---

## Function and Module Design

### Functions should:
- do one coherent thing
- have clear inputs and outputs
- avoid hidden mutations unless clearly intended
- be easy to test in isolation where appropriate

### Prefer
- short to medium-sized functions
- explicit parameter names
- extracted helpers when they improve readability
- early returns for guard conditions

### Avoid
- giant multi-purpose functions
- deep nested conditionals when simpler flow is possible
- long parameter lists when a meaningful object improves clarity
- functions that mix validation, persistence, formatting, and side effects without structure

### Parameter design
Prefer:
- explicit parameters for simple functions
- small typed objects for larger input surfaces
- consistent ordering when patterns repeat

Do not pass giant loosely-typed bags of data everywhere.

### Return values
Prefer:
- predictable return shapes
- typed results
- values that are easy to compose
- explicit nullability or error behavior

Avoid:
- return types that vary wildly by branch
- magical sentinel values without documentation
- silently ambiguous results

---

## TypeScript / Type Safety Conventions

Use the type system to clarify boundaries and prevent bugs, not to perform type gymnastics for sport.

### Prefer
- strict typing
- explicit boundary types
- inferred local types when obvious
- domain types near the domain
- schema-backed validation at external boundaries

### Avoid
- `any` unless temporary and clearly justified
- broad type assertions used to silence real uncertainty
- over-engineered generic types no one can read
- giant shared type dumping grounds

### Use interfaces vs types
Use whatever the repo prefers. If no preference exists:
- use `type` for unions, mapped types, and most application types
- use `interface` when modeling extendable object shapes if that improves clarity

Consistency matters more than ideology.

### Type assertions
Use assertions sparingly.

Allowed when:
- narrowing is logically guaranteed but the type system cannot express it cleanly
- interfacing with poorly typed third-party APIs
- bridging unavoidable framework gaps

Not allowed as a lazy substitute for proper typing.

### Enums
Prefer literal unions or const objects unless the repo already uses enums heavily.

### Nullability
Be honest about null/undefined possibilities.  
Do not pretend impossible states are impossible unless they truly are.

### Boundary typing
Type these especially carefully:
- API inputs
- API outputs
- database records transformed for app use
- environment variables
- third-party responses
- auth/session payloads
- form submissions

These are bug multipliers if left loose.

---

## Data and State Conventions

### Keep state minimal
Store only what needs to be stored.

Prefer:
- deriving values when cheap and clear
- a single source of truth
- reducing duplicated state

Avoid:
- mirrored state
- stale derived copies
- state that exists only to compensate for poor structure

### State ownership
State should live at the narrowest level that can own it responsibly.

Prefer:
- local state for local concerns
- shared state only when truly shared
- server-owned state for server truth
- URL state for navigational/filter/shareable state

### Data transformation
Keep transformations:
- explicit
- named when non-trivial
- close to their usage or domain boundary

Avoid chains so dense that no one can tell what the data looks like anymore.

---

## React / UI Conventions

Use these when working in React-style UI code.

### Components should:
- have a clear responsibility
- be easy to scan
- avoid mixing deep business rules with UI rendering
- accept explicit props
- delegate complexity when it grows

### Prefer
- small composable components
- presentational components separated from heavy business logic where useful
- clear prop names
- semantic HTML
- predictable state flow

### Avoid
- giant components with rendering, fetching, permissions, state orchestration, and business rules all mixed together
- prop drilling so deep that ownership is unclear
- global state for problems that are local
- “reusable” components that are actually one feature in disguise

### Props
Prefer:
- small explicit prop surfaces
- domain-oriented prop names
- booleans only when they model a real binary state
- composition over over-configurable components

Avoid:
- prop APIs that try to serve every future use case
- huge option surfaces that make the component hard to reason about

### Hooks
Hooks should:
- encapsulate meaningful UI or feature logic
- expose clean, stable interfaces
- avoid hiding surprising side effects

Do not use hooks as a dumping ground for arbitrary business logic.

### Conditional rendering
Prefer:
- explicit branches
- extracted subcomponents when conditional logic becomes noisy

Avoid unreadable JSX with many nested ternaries.

---

## Server / Backend Conventions

### Handlers and controllers
Handlers should:
- parse inputs
- delegate to domain/service logic
- map outputs
- handle error translation where appropriate

They should not:
- contain deep business rules
- become the main home of domain logic
- duplicate validation logic repeatedly

### Services / domain modules
Services should:
- model real business behavior
- expose clear interfaces
- centralize domain rules that matter
- remain testable

Avoid turning service layers into vague pass-through wrappers.

### Persistence
Keep database access:
- explicit
- near the owning feature/domain/data layer
- predictable in behavior

Avoid:
- scattered direct writes from unrelated files
- mixed read/write patterns with unclear ownership
- hiding writes inside innocent-looking helpers

### External integrations
Wrap third-party systems deliberately.

Prefer:
- local adapters
- normalized responses
- explicit failure handling
- clear ownership

Avoid leaking vendor-specific details across the whole app.

---

## Validation Conventions

Validate at boundaries.

### Always validate external or unsafe input
This includes:
- HTTP requests
- form data
- environment variables
- webhook payloads
- third-party API responses when trust is limited
- file input
- query params when they affect behavior

### Prefer
- schema validation
- clear error messages
- normalization close to validation
- one source of truth for critical shapes

### Avoid
- scattered ad hoc checks
- partial validation that creates false confidence
- trusting user input because “the UI already prevents it”

---

## Error Handling Conventions

Errors should be:
- deliberate
- understandable
- useful for debugging
- safe for users

### Prefer
- clear error boundaries
- explicit handling where failure is expected
- consistent result/error patterns within a subsystem
- preserving useful context internally

### Avoid
- swallowed errors
- vague catch-all behavior
- returning `null` for everything without meaning
- leaking secrets or internal details to users

### Error messages
For internal/debuggable contexts:
- be specific enough to diagnose

For user-facing contexts:
- be clear, calm, and safe
- avoid exposing internals

### Catch blocks
Do not add catch blocks that only hide failure.  
Catch to:
- add context
- translate errors
- recover meaningfully
- clean up side effects

---

## Comments and Documentation in Code

Comments should earn their existence.

### Good reasons to comment
- explaining non-obvious constraints
- documenting surprising tradeoffs
- clarifying why a weird-looking decision exists
- noting protocol/business rules that code alone does not make obvious

### Bad reasons to comment
- restating obvious code
- narrating trivial steps
- compensating for poor naming
- leaving stale implementation descriptions

### Prefer
- code that explains itself through structure and naming
- small precise comments when needed
- doc comments for exported APIs only when they add real value

### Avoid
- comment noise
- giant header essays in routine files
- TODO graveyards

---

## Imports and Dependencies

### Imports should be:
- minimal
- explicit
- ordered according to repo convention
- free of unused symbols

### Prefer
- importing from stable local modules
- preserving boundary clarity
- using existing utilities before creating new ones

### Avoid
- deep fragile imports when stable public imports exist
- circular import patterns
- importing broad utility bags when only one specific function is needed

### New dependencies
Do not add a dependency unless:
- existing repo tools cannot solve the problem well
- the benefit is clear
- the maintenance cost is justified

Each dependency should earn its keep.

---

## Configuration Conventions

Configuration should be:
- centralized where practical
- typed or validated where possible
- easy to discover
- explicit about environment assumptions

### Prefer
- validated environment variables
- one clear place for important config
- descriptive env var names
- safe defaults where appropriate

### Avoid
- config hidden across random files
- magic constants with unclear origin
- environment behavior that changes silently

---

## Logging Conventions

Logs should help diagnose real issues, not create noise.

### Prefer
- structured logs where appropriate
- contextual logs around side effects and failures
- meaningful event names
- redaction of sensitive data

### Avoid
- noisy debug spam left in production code
- logging secrets, tokens, or personal data
- vague logs like “here” or “done”

### Console usage
Temporary debugging is fine during work.  
Do not leave stray debug logs behind unless they are intentional and useful.

---

## Testing-Oriented Coding Conventions

Write code that can be verified without heroics.

### Prefer
- deterministic behavior
- small composable units
- explicit side-effect boundaries
- clear return values
- extracted domain logic for important workflows

### Avoid
- logic embedded only in UI event handlers when it could be tested more directly
- giant hidden state machines without structure
- hard-coded environment assumptions
- implicit dependencies that make testing painful

If code is difficult to test, that is often a design signal.

---

## Performance Conventions

Do not optimize by reflex.

### Prefer
- correct and clear code first
- profiling or evidence before complex optimization
- removing unnecessary work
- choosing good data access patterns
- memoization only when it solves a demonstrated issue or is a clear local win

### Avoid
- premature micro-optimizations
- readability sacrifice for hypothetical speed
- widespread memoization cargo cults
- hand-rolled complexity before measuring

Performance matters.  
Performance theater does not.

---

## Security Conventions

Security-sensitive code requires extra discipline.

### Always be careful with:
- auth
- permissions
- file access
- secrets
- billing/payment
