"""Agent-agnostic data model for a single coding-agent session."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Usage:
    input: int = 0          # uncached input tokens
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_write + self.cache_read

    def add(self, other: "Usage") -> None:
        self.input += other.input
        self.output += other.output
        self.cache_write += other.cache_write
        self.cache_read += other.cache_read


@dataclass
class Action:
    kind: str                 # "command" | "write" | "read" | "web" | "tool"
    tool: str                 # raw tool name
    target: str               # command text, file path, url/query
    ts: Optional[datetime] = None
    failed: bool = False


@dataclass
class Flag:
    severity: str             # "high" | "medium" | "low"
    rule: str                 # short label
    detail: str               # the offending command / path


@dataclass
class Session:
    agent: str                # "Claude Code" | "Codex"
    session_id: str
    path: str
    cwd: str = ""
    git_branch: str = ""
    models: dict = field(default_factory=dict)   # model -> Usage
    actions: list = field(default_factory=list)
    prompts: int = 0
    first_prompt: str = ""
    started: Optional[datetime] = None
    ended: Optional[datetime] = None
    flags: list = field(default_factory=list)

    # ---- derived -------------------------------------------------------
    @property
    def usage(self) -> Usage:
        u = Usage()
        for m in self.models.values():
            u.add(m)
        return u

    @property
    def duration_s(self) -> float:
        if self.started and self.ended:
            return max(0.0, (self.ended - self.started).total_seconds())
        return 0.0

    def of_kind(self, kind: str) -> list:
        return [a for a in self.actions if a.kind == kind]

    @property
    def files_written(self) -> list:
        seen, out = set(), []
        for a in self.of_kind("write"):
            if a.target not in seen:
                seen.add(a.target)
                out.append(a.target)
        return out

    @property
    def files_read(self) -> list:
        return sorted({a.target for a in self.of_kind("read")})

    @property
    def commands(self) -> list:
        return self.of_kind("command")

    @property
    def failures(self) -> int:
        return sum(1 for a in self.actions if a.failed)
