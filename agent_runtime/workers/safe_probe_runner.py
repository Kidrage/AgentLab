"""Safe probe runner to execute worker contract safe probe commands."""

import subprocess
import shutil
from typing import Optional
from agent_runtime.workers.invocation_contract import WorkerInvocationContract

def run_safe_probe(
    contract: WorkerInvocationContract, 
    mock: bool = False
) -> tuple[Optional[int], str, str, bool, bool]:
    """
    Run the safe probe command from the contract.
    Returns: (exit_code, stdout, stderr, timeout_occurred, binary_missing)
    """
    if not contract.safe_probe:
        return 0, "No safe probe command configured", "", False, False

    # Under mock mode, simulate execution
    if mock:
        # We can simulate command existence based on path discovery or simple flags
        simulated_installed = shutil.which(contract.command) is not None
        if simulated_installed:
            return 0, "mock version 1.0.0", "", False, False
        else:
            return None, "", f"Command '{contract.command}' not found", False, True

    # Real execution
    try:
        # Check command presence first
        if not shutil.which(contract.command):
            return None, "", f"Command '{contract.command}' not found", False, True

        res = subprocess.run(
            contract.safe_probe,
            capture_output=True,
            text=True,
            timeout=2.0
        )
        return res.returncode, res.stdout, res.stderr, False, False
    except subprocess.TimeoutExpired:
        return None, "", "Command execution timed out", True, False
    except FileNotFoundError:
        return None, "", f"Command '{contract.command}' not found", False, True
    except Exception as e:
        return None, "", f"Execution failed: {str(e)}", False, False
