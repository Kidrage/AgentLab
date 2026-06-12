from pathlib import Path
from typing import Any, Callable, Optional
import functools
import yaml
import json
import os

def atomic_write_text(path: str, content: str, mode: str = 'w') -> None:
    """Write text to a file atomically"""
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    # Create a temporary file
    temp_path = path_obj.with_suffix(path_obj.suffix + '.tmp')
    
    try:
        # Write to temporary file
        with open(temp_path, mode) as f:
            f.write(content)
        
        # Move to final destination
        temp_path.replace(path_obj)
    finally:
        # Clean up if temporary file exists
        if temp_path.exists():
            os.unlink(temp_path)

def atomic_write_yaml(path: str, data: Any, mode: str = 'w') -> None:
    """Write YAML data to a file atomically"""
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    temp_path = path_obj.with_suffix(path_obj.suffix + '.tmp')
    
    try:
        # Write to temporary file
        with open(temp_path, mode) as f:
            yaml.safe_dump(data, f, sort_keys=False)
        
        # Move to final destination
        temp_path.replace(path_obj)
    finally:
        # Clean up if temporary file exists
        if temp_path.exists():
            os.unlink(temp_path)

def atomic_write_json(path: str, data: Any, mode: str = 'w') -> None:
    """Write JSON data to a file atomically"""
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    temp_path = path_obj.with_suffix(path_obj.suffix + '.tmp')
    
    try:
        # Write to temporary file
        with open(temp_path, mode) as f:
            json.dump(data, f, indent=2)
        
        # Move to final destination
        temp_path.replace(path_obj)
    finally:
        # Clean up if temporary file exists
        if temp_path.exists():
            os.unlink(temp_path)

def atomic_read_text(path: str) -> str:
    """Read text from a file with atomic operation"""
    with open(path, 'r') as f:
        return f.read()

def atomic_read_yaml(path: str) -> Any:
    """Read YAML from a file with atomic operation"""
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def atomic_read_json(path: str) -> Any:
    """Read JSON from a file with atomic operation"""
    with open(path, 'r') as f:
        return json.load(f)

def with_atomic_write(mode: str = 'w') -> Callable:
    """Decorator for atomic write operations"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            path = kwargs.get('path', args[0] if args else None)
            if not path:
                raise ValueError("Path must be specified for atomic write")
                
            path_obj = Path(path)
            temp_path = path_obj.with_suffix(path_obj.suffix + '.tmp')
            
            try:
                result = func(*args, **kwargs)
                # If function returns content, write it atomically
                if result is not None:
                    with open(temp_path, mode) as f:
                        f.write(result)
                    temp_path.replace(path_obj)
                return result
            finally:
                # Clean up if temporary file exists
                if temp_path.exists():
                    os.unlink(temp_path)
        return wrapper
    return decorator