# M2U4OC - Memory To Use For OpenClaw

**Version:** 1.0.0  
**Purpose:** Export Claw's memory and agent logic as a reusable skill

## What This Does

M2U4OC replicates the cognitive abilities of an advanced OpenClaw agent:

1. **Long-term Memory** - Persistent storage across sessions
2. **Session Context** - Knows who you are, who you're helping
3. **Learning** - Remembers important decisions and context
4. **Daily Notes** - Timestamped session logs
5. **Search** - Find relevant past information

## Files

| File | Purpose |
|------|---------|
| `memory_agent.py` | Core Python module with MemoryAgent class |
| `memory-agent-skill.json` | Skill configuration for OpenClaw |
| `setup.sh` | Easy installation script |
| `SYSTEM_PROMPT.md` | Context loading instructions |

## Quick Setup

```bash
# Run the setup
chmod +x setup.sh
./setup.sh /path/to/your/openclaw/workspace
```

## Manual Setup

1. Copy `memory_agent.py` to your workspace
2. Run: `python3 memory_agent.py /path/to/workspace`
3. Edit the created files (MEMORY.md, SOUL.md, USER.md)
4. Add to your agent's system prompt:

```
## Agent Context System

At the start of each session:
1. Read SOUL.md - This defines who you are
2. Read USER.md - This defines who you're helping  
3. Read MEMORY.md - Long-term memories
4. Read today's memory file - Recent context

When remembering important information:
- Write to memory/YYYY-MM-DD.md for daily notes
- Update MEMORY.md for permanent memories
```

## Files Created

After running, these files will be created:

```
workspace/
├── MEMORY.md          # Long-term memory (persists forever)
├── SOUL.md           # Agent identity & personality
├── USER.md           # User preferences & context
└── memory/
    └── YYYY-MM-DD.md # Daily session notes
```

## Usage Examples

### Save important info
```python
from memory_agent import MemoryAgent

agent = MemoryAgent("./workspace")
agent.save_daily_note("Learned that user prefers short responses")

agent.update_longterm_memory("Skills Installed", "- humanizer\n- proactive-claw")
```

### Load context at session start
```python
agent = MemoryAgent("./workspace")
context = agent.load_context()

# Use in your system prompt
system_prompt = f"""
You are {context['soul']}
Helping {context['user']}
Known: {context['memory'][:500]}...
"""
```

### Search past conversations
```python
results = agent.search_memory("preferences")
for r in results:
    print(f"Found in {r['source']}: {r['content'][:200]}")
```

## Key Features

- **No database required** - Uses plain Markdown files
- **Automatic daily notes** - Timestamped entries
- **Semantic search** - Find relevant past info
- **Version aware** - Tracks what changed when
- **Portable** - Just copy the files to new installations

## Integration with OpenClaw

Add to your gateway.yaml:

```yaml
skills:
  - name: memory-agent
    enabled: true
    config:
      workspace: ./workspace
      auto_save: true
```

## Credits

Built by Ryan & Claw 🦞

Inspired by OpenClaw's advanced agent capabilities.
