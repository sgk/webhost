#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(path)
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def format_env_vars(values: dict[str, str]) -> str:
    items = []
    for key, value in values.items():
        escaped = value.replace(",", "\\,")
        items.append(f"{key}={escaped}")
    return ",".join(items)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env-deploy")
    parser.add_argument("--get")
    parser.add_argument("--env-vars", action="store_true")
    args = parser.parse_args()

    values = parse_env(Path(args.env_file))

    if args.get:
        print(values.get(args.get, ""))
        return 0

    if args.env_vars:
        print(format_env_vars(values))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

