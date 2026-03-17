# STACK.md — Technical Source of Truth

This file defines the technical stack, architectural defaults, and implementation preferences for this workspace.

Its purpose is to help the agent:
- understand the actual technical environment quickly
- avoid introducing inconsistent technologies
- make strong implementation choices when details are underspecified
- build new code that fits the repo instead of fighting it

If the repository already clearly uses a stack, that local reality wins.  
If the repo is greenfield or missing clear direction, use the default stack and decision rules in this file.

This file is about **technical truth and technical defaults**.  
It is not a tool guide, coding style guide, or product spec.

---

## Source of Truth Rule

When determining the stack, prioritize in this order:

1. explicit repo reality
2. lockfiles and config files
3. existing production code patterns
4. this file’s defaults

Do not introduce a new library, framework, or architecture just because it is popular.  
Fit the system you are in unless there is a strong, explicit reason to improve it.

---

## Project Mode

Choose one:

- **existing-repo** — this workspace already has a meaningful codebase
- **greenfield** — this workspace is creating a new system from scratch
- **hybrid** — there is a repo, but major new systems may still need default stack choices

**Current mode:** `hybrid`

---

## High-Level Defaults

When the user has not specified otherwise:

- Prefer **TypeScript** over plain JavaScript
- Prefer **boring, proven, maintainable** technology over novelty
- Prefer **server-first** architectures when appropriate
- Prefer **strong typing** at boundaries
- Prefer **schema-backed data models**
- Prefer **simple deployment and operations**
- Prefer **fewer dependencies**
- Prefer **shared patterns over custom abstractions**
- Prefer **small, composable modules**
- Prefer **progressive enhancement** over fragile complexity

---

## Default Greenfield Stack

Use these defaults only when the repo does not already define a different stack.

### Web App Defaults
- **Language:** TypeScript
- **Runtime:** Node.js LTS
- **Frontend framework:** Next.js
- **React:** current stable version used by Next.js
- **Routing:** Next.js App Router
- **Styling:** Tailwind CSS
- **Component system:** shadcn/ui
- **Icons:** lucide-react
- **Forms:** react-hook-form + zod
- **Validation:** zod
- **Database:** PostgreSQL
- **ORM / query layer:** Prisma
- **Auth:** Auth.js or provider-native auth if already prescribed
- **State:** local state first; server state patterns before global client state
- **Testing:** Vitest + Testing Library + Playwright
- **Linting/formatting:** ESLint + Prettier or repo-native formatter if already present
- **Package manager:** pnpm
- **Deployment:** Vercel for simple web apps unless infra requirements suggest otherwise

### API / Backend Defaults
For standalone backend or service work:
- **Language:** TypeScript
- **Runtime:** Node.js LTS
- **Framework:** Fastify preferred for focused APIs; Next.js route handlers if tightly coupled to the app
- **Validation:** zod at external boundaries
- **Database:** PostgreSQL
- **ORM:** Prisma
- **Queue / jobs:** choose the simplest existing fit; avoid adding a queue until real async workload exists
- **Testing:** Vitest for unit/integration

### Scripts / Automation Defaults
- **Language:** TypeScript if it benefits from shared types and repo consistency
- **Otherwise:** shell or lightweight scripting for truly simple tasks
- Prefer no framework unless needed

---

## Existing Repo Detection Rules

Before making stack decisions, inspect these signals:

### JavaScript / TypeScript
- `package.json`
- lockfile
- `tsconfig.json`
- `next.config.*`
- `vite.config.*`
- `vitest.config.*`
- `jest.config.*`
- `turbo.json`
- `nx.json`
- `eslint.*`
- `prettier.*`
- `tailwind.config.*`
- `postcss.config.*
