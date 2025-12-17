import subprocess
import sys
from pathlib import Path
from typing import Optional


def generate_proto(
    proto_file: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    proto_path: Optional[Path] = None,
) -> bool:
    script_dir = Path(__file__).parent.resolve()

    if proto_file is None:
        proto_file = script_dir / "models" / "semantic_graph.proto"
    else:
        proto_file = Path(proto_file).resolve()

    if output_dir is None:
        output_dir = proto_file.parent
    else:
        output_dir = Path(output_dir).resolve()

    if proto_path is None:
        proto_path = proto_file.parent
    else:
        proto_path = Path(proto_path).resolve()

    if not proto_file.exists():
        print(f"Error: Proto file not found: {proto_file}")
        return False

    try:
        subprocess.run(
            [
                "protoc",
                f"--proto_path={proto_path}",
                f"--python_out={output_dir}",
                str(proto_file),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        print("✓ Successfully generated protobuf bindings")
        print(f"  Output: {output_dir / proto_file.stem}_pb2.py")
        return True
    except FileNotFoundError:
        print(
            "Error: 'protoc' not found. Please ensure protoc is installed and in your PATH."
        )
        return False
    except subprocess.CalledProcessError as e:
        print(f"Error: protoc failed: {e.stderr}")
        return False


if __name__ == "__main__":
    success = generate_proto()
    sys.exit(0 if success else 1)
