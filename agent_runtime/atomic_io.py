from pathlib import Path
from typing import Any, Callable, Optional
import functools
import yaml
import json
import os

def atomic_write_text(path, content, encoding="utf-8"):
    """Write text to a file atomically."""
    path_obj = Path(str(path))
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path_obj.with_suffix(path_obj.suffix + '.tmp')
    try:
        with open(temp_path, 'w', encoding=encoding) as f:
            f.write(content)
        temp_path.replace(path_obj)
    finally:
        if temp_path.exists():
            os.unlink(temp_path)

def atomic_write_yaml(path, data, sort_keys=False, allow_unicode=True):
    """Write YAML data to a file atomically."""
    path_obj = Path(str(path))
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path_obj.with_suffix(path_obj.suffix + '.tmp')
    try:
        content = yaml.safe_dump(data, sort_keys=sort_keys, allow_unicode=allow_unicode)
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(content)
        temp_path.replace(path_obj)
    finally:
        if temp_path.exists():
            os.unlink(temp_path)

def atomic_write_json(path, data):
    """Write JSON data to a file atomically."""
    path_obj = Path(str(path))
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path_obj.with_suffix(path_obj.suffix + '.tmp')
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_path.replace(path_obj)
    finally:
        if temp_path.exists():
            os.unlink(temp_path)

def atomic_read_text(path, encoding="utf-8"):
    """Read text from a file."""
    with open(str(path), 'r', encoding=encoding) as f:
        return f.read()

def atomic_read_yaml(path):
    """Read YAML from a file."""
    with open(str(path), 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def atomic_read_json(path):
    """Read JSON from a file."""
    with open(str(path), 'r', encoding='utf-8') as f:
        return json.load(f)

def safe_read_yaml(path):
    """Safely read YAML file, returning empty dict on failure."""
    try:
        return atomic_read_yaml(path) or {}
    except Exception:
        return {}

def safe_read_json(path):
    """Safely read JSON file, returning empty dict on failure."""
    try:
        return atomic_read_json(path) or {}
    except Exception:
        return {}

def safe_read_text(path, encoding="utf-8"):
    """Safely read text file, returning empty string on failure."""
    try:
        return atomic_read_text(path, encoding)
    except Exception:
        return ""

def with_atomic_write(mode='w'):
    """Decorator for atomic write operations."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            path = kwargs.get('path', args[0] if args else None)
            if not path:
                raise ValueError("Path must be specified for atomic write")
            path_obj = Path(str(path))
            temp_path = path_obj.with_suffix(path_obj.suffix + '.tmp')
            try:
                result = func(*args, **kwargs)
                if result is not None:
                    with open(temp_path, mode) as f:
                        f.write(result)
                    temp_path.replace(path_obj)
                return result
            finally:
                if temp_path.exists():
                    os.unlink(temp_path)
        return wrapper
    return decorator