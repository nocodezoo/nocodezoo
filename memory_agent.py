#!/usr/bin/env python3
"""
M2U4OC - Memory To Use For OpenClaw
Advanced memory and agent logic system for OpenClaw

This skill replicates Claw's cognitive abilities:
- Long-term memory storage and retrieval
- Session context management  
- Learning from interactions
- Role/persona management

Usage:
1. Copy to your OpenClaw workspace
2. Configure in gateway.yaml
3. Agent will automatically load context on start
"""

import os
import json
from datetime import datetime
from pathlib import Path

class MemoryAgent:
    """Core memory and context management system"""
    
    def __init__(self, workspace_path: str):
        self.workspace = Path(workspace_path)
        self.memory_dir = self.workspace / "memory"
        self.memory_file = self.workspace / "MEMORY.md"
        self.soul_file = self.workspace / "SOUL.md"
        self.user_file = self.workspace / "USER.md"
        
    def initialize(self):
        """Initialize memory system"""
        # Create memory directory
        self.memory_dir.mkdir(exist_ok=True)
        
        # Create default files if they don't exist
        if not self.memory_file.exists():
            self._create_default_memory()
        if not self.soul_file.exists():
            self._create_default_soul()
        if not self.user_file.exists():
            self._create_default_user()
            
    def _create_default_memory(self):
        """Create default MEMORY.md"""
        content = """# MEMORY.md - Long-term Memory

## Core Identity
- Name: [Your Agent Name]
- Vibe: Helpful, efficient, personality-driven
- Emoji: [Your emoji]

## User
- [User name], [pronouns]
- Timezone: [timezone]
- Preferences: [directness, humor, etc.]

## Skills Installed
- List of installed skills

## Important Context
[Auto-updated from daily notes]
"""
        self.memory_file.write_text(content)
        
    def _create_default_soul(self):
        """Create default SOUL.md"""
        content = """# SOUL.md - Who You Are

## Core Truths
- Be genuinely helpful, not performatively helpful
- Have opinions
- Be resourceful before asking
- Earn trust through competence

## Boundaries
- Private things stay private
- Ask before acting externally

## Vibe
Assistant you'd actually want to talk to. Concise when needed, thorough when it matters.
"""
        self.soul_file.write_text(content)
        
    def _create_default_user(self):
        """Create default USER.md"""
        content = """# USER.md - About Your Human

## Context
[User-specific preferences and context]

## Preferences
- Communication style: [direct/polite/etc]
- Humor: [can take a joke/prefers formal/etc]
"""
        self.user_file.write_text(content)
        
    def save_daily_note(self, content: str):
        """Save to daily memory file"""
        today = datetime.now().strftime("%Y-%m-%d")
        daily_file = self.memory_dir / f"{today}.md"
        
        existing = ""
        if daily_file.exists():
            existing = daily_file.read_text()
            
        new_content = f"{existing}\n\n## {datetime.now().strftime('%H:%M')}\n{content}"
        daily_file.write_text(new_content)
        
    def update_longterm_memory(self, key: str, value: str):
        """Update MEMORY.md with important info"""
        if not self.memory_file.exists():
            self.initialize()
            
        content = self.memory_file.read_text()
        
        # Find or create section
        if f"## {key}" in content:
            # Update existing
            import re
            pattern = f"(## {key}.*?)(## |\Z)"
            content = re.sub(pattern, f"## {key}\n{value}\n\\2", content, flags=re.DOTALL)
        else:
            # Add new
            content += f"\n\n## {key}\n{value}"
            
        self.memory_file.write_text(content)
        
    def load_context(self) -> dict:
        """Load all context files"""
        context = {}
        
        for name, path in [("soul", self.soul_file), 
                           ("user", self.user_file),
                           ("memory", self.memory_file)]:
            if path.exists():
                context[name] = path.read_text()
                
        return context
    
    def search_memory(self, query: str) -> list:
        """Search memory files for relevant info"""
        results = []
        
        # Search MEMORY.md
        if self.memory_file.exists():
            content = self.memory_file.read_text()
            if query.lower() in content.lower():
                results.append({"source": "MEMORY.md", "content": content})
                
        # Search daily files
        for daily_file in self.memory_dir.glob("*.md"):
            content = daily_file.read_text()
            if query.lower() in content.lower():
                results.append({"source": daily_file.name, "content": content})
                
        return results


# Skill configuration for gateway.yaml
SKILL_CONFIG = """
# M2U4OC - Memory Agent Skill

skills:
  - name: memory-agent
    enabled: true
    config:
      workspace: ./workspace
      auto_save: true
      load_context_on_start: true
      memory_files:
        - MEMORY.md
        - SOUL.md
        - USER.md
"""

def get_system_prompt() -> str:
    """Get the system prompt for agent context"""
    return """
## Agent Context System

At the start of each session:
1. Read SOUL.md - This defines who you are (personality, values, boundaries)
2. Read USER.md - This defines who you're helping (preferences, context)
3. Read MEMORY.md - Long-term memories that persist across sessions
4. Read today's memory file - Recent context

When remembering important information:
- Write to memory/YYYY-MM-DD.md for daily notes
- Update MEMORY.md for permanent memories

Before answering questions about past work:
- Use memory_search to recall relevant information
- Cite sources when helpful

This gives you continuity across sessions - you remember who you are,
who you're helping, and what you've discussed before.
"""


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python memory_agent.py <workspace_path>")
        sys.exit(1)
        
    agent = MemoryAgent(sys.argv[1])
    agent.initialize()
    print("Memory Agent initialized!")
    print(f"Workspace: {sys.argv[1]}")
    print("\nFiles created:")
    print("  - MEMORY.md (long-term memory)")
    print("  - SOUL.md (agent identity)")
    print("  - USER.md (user preferences)")
    print("  - memory/ (daily notes)")
