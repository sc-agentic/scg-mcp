"""
Project configuration for Semantic Graph RAG.

Choose which project to analyze by setting the SCG_PROJECT environment variable
or passing --project <name> as a CLI argument.

To register a new project, add an entry to the PROJECTS dict below.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ── Project registry ─────────────────────────────────────────────────────────
# Each key is the project's short name.
# `data_dir` and `code_dir` are relative to the repository root.

PROJECTS: dict[str, dict[str, str]] = {
    "glide": {
        "data_dir": "data/glide",
        "code_dir": "code/glide-4.5.0",
    },
    "private_repo": {
        "data_dir": "data/private_repo",
        "code_dir": "code/private_repo",
    },
}

DEFAULT_PROJECT = "private_repo"


# ── Resolved config ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProjectConfig:
    name: str
    data_dir: Path
    code_dir: Path

    @property
    def cache_path(self) -> Path:
        return self.data_dir / ".embeddings_cache.pt"


def get_project_config(project_name: Optional[str] = None) -> ProjectConfig:
    """Resolve the active project.

    Resolution order:
      1. Explicit *project_name* argument (used by callers that parse their own CLI).
      2. ``--project`` CLI flag (auto-parsed from ``sys.argv``).
      3. ``SCG_PROJECT`` environment variable.
      4. ``DEFAULT_PROJECT`` constant defined above.
    """
    name = project_name

    # 2. Try CLI arg (only when not provided explicitly)
    if name is None:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--project", type=str, default=None)
        known, _ = parser.parse_known_args()
        name = known.project

    # 3. Try env var
    if name is None:
        name = os.environ.get("SCG_PROJECT")

    # 4. Fallback
    if name is None:
        name = DEFAULT_PROJECT

    if name not in PROJECTS:
        available = ", ".join(sorted(PROJECTS.keys()))
        print(
            f"Error: Unknown project '{name}'. Available projects: {available}",
            file=sys.stderr,
        )
        sys.exit(1)

    entry = PROJECTS[name]
    return ProjectConfig(
        name=name,
        data_dir=Path(entry["data_dir"]),
        code_dir=Path(entry["code_dir"]),
    )
