"""Validator for worker CLI command templates."""

import shlex
import re
# typing imports removed, using built-in list and tuple

def validate_template(
    template: str, 
    required_placeholders: list[str], 
    allow_unquoted_placeholders: bool = False
) -> tuple[bool, list[str]]:
    """Validate a CLI command template against grammar and placeholder requirements."""
    errors = []

    # 1. Check all required placeholders are physically declared in the template
    found_placeholders = set(re.findall(r'\{([a-zA-Z0-9_]+)\}', template))
    for placeholder in required_placeholders:
        if placeholder not in found_placeholders:
            errors.append(f"Required placeholder '{placeholder}' is missing from the command template")

    # 2. Check for unquoted placeholders (except for 'args')
    if not allow_unquoted_placeholders:
        for placeholder in required_placeholders:
            if placeholder == "args":
                continue
            if placeholder in found_placeholders:
                # If neither double nor single quotes wrap the placeholder
                if f'"{{{placeholder}}}"' not in template and f"'{{{placeholder}}}'" not in template:
                    errors.append(
                        f"Placeholder '{placeholder}' must be quoted in template to prevent shell injection/splitting issues"
                    )

    # 3. Format and test shlex parsing
    dummy_values = {p: f"dummy_{p}" for p in found_placeholders}
    try:
        formatted_cmd = template.format(**dummy_values)
        try:
            shlex.split(formatted_cmd)
        except ValueError as e:
            errors.append(f"shlex parse failure: {str(e)}")
    except KeyError as e:
        errors.append(f"Template formatting failed due to missing key: {str(e)}")
    except Exception as e:
        errors.append(f"Formatting failed: {str(e)}")

    return len(errors) == 0, errors
