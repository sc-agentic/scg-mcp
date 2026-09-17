import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PROJECTS: dict[str, dict[str, str]] = {
    "glide": {
        "data_dir": "../scg-benchmark-ca/codebases/glide-5.0.5",
        "code_dir": "../scg-benchmark-ca/codebases/glide-5.0.5",
    },
    "daytrader7": {
        "data_dir": "../scg-benchmark-ca/codebases/daytrader7",
        "code_dir": "../scg-benchmark-ca/codebases/daytrader7",
    },
    "petclinic": {
        "data_dir": "../scg-decompose-bench/codebases/petclinic",
        "code_dir": "../scg-decompose-bench/codebases/petclinic",
    },
    "acmeair": {
        "data_dir": "../scg-decompose-bench/codebases/acmeair",
        "code_dir": "../scg-decompose-bench/codebases/acmeair",
    },
    "private_repo": {
        "data_dir": "data/private_repo",
        "code_dir": "code/private_repo",
    },
}

DEFAULT_PROJECT = "private_repo"


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    data_dir: Path
    code_dir: Path

    @property
    def cache_path(self) -> Path:
        return self.data_dir / ".embeddings_cache.pt"


def get_project_config(project_name: Optional[str] = None) -> ProjectConfig:
    name = project_name

    if name is None:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--project", type=str, default=None)
        known, _ = parser.parse_known_args()
        name = known.project

    if name is None:
        name = os.environ.get("SCG_PROJECT")

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
