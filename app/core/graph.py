"""Graph loader: merges all JSON files from data/graph/ into a single global dictionary."""

from pathlib import Path
import json
from typing import Any


def load_graph(graph_dir: Path | str | None = None) -> dict[str, Any]:
    """
    Load and merge all .json files from data/graph/ into a single dictionary.

    Args:
        graph_dir: Path to graph directory. Defaults to data/graph/ relative to project root.

    Returns:
        Merged dictionary where key = node_id.

    Raises:
        FileNotFoundError: If graph_dir does not exist.
        ValueError: If duplicate node_id found across files.
    """
    if graph_dir is None:
        graph_dir = Path(__file__).resolve().parent.parent.parent / "data" / "graph"

    graph_path = Path(graph_dir)
    if not graph_path.is_dir():
        raise FileNotFoundError(f"Graph directory not found: {graph_path}")

    global_graph: dict[str, Any] = {}

    for json_file in sorted(graph_path.glob("*.json")):
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(
                f"File {json_file.name} must contain a JSON object, got {type(data).__name__}"
            )

        for node_id, node_data in data.items():
            if node_id in global_graph:
                raise ValueError(
                    f"Duplicate node_id '{node_id}' found: "
                    f"both in {json_file.name} and in previously loaded file"
                )
            global_graph[node_id] = node_data

    return global_graph


def get_root_node_id(global_graph: dict[str, Any]) -> str:
    """
    Get the root node ID. Expects a node named 'root' in the graph.

    Args:
        global_graph: The merged graph dictionary.

    Returns:
        The node_id of the root node.

    Raises:
        KeyError: If 'root' node is not found.
    """
    if "root" not in global_graph:
        raise KeyError("Root node 'root' not found in graph. Ensure _root.json defines it.")
    return "root"
