import argparse
import yaml
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from agent_runtime.external_agents.registry import registry as agent_registry
from agent_runtime.external_agents.handoff import ExternalHandoff
from agent_runtime.external_agents.result import ExternalResult
from agent_runtime.external_agents.ledger import ExternalAgentLedger

def list_agents(args: argparse.Namespace) -> None:
    """List configured external agents"""
    agents = agent_registry.list_agents()
    print("\nExternal Agents:")
    print("-" * 60)
    for agent in agents:
        print(f"\nID: {agent['agent_id']}")
        print(f"Name: {agent['display_name']}")
        print(f"Type: {agent['type']}")
        print(f"Enabled: {agent['enabled']}")
        print(f"Integration Mode: {agent['integration_mode']}")
        print(f"Risk Level: {agent['risk']['level']}")
        print("-" * 60)

def create_handoff(args: argparse.Namespace) -> None:
    """Create a new external agent handoff"""
    try:
        handoff = ExternalHandoff(args.task_id, args.output_dir)
        result = handoff.create_handoff(args.agent_id, args.title, args.summary)
        
        print("\nHandoff Created Successfully:")
        print("-" * 60)
        print(yaml.safe_dump(result, sort_keys=False))
        print("-" * 60)
        print(f"Artifacts saved to: {handoff.output_dir}")
        
    except Exception as e:
        print(f"Error creating handoff: {str(e)}")
        sys.exit(1)

def submit_result(args: argparse.Namespace) -> None:
    """Submit an external agent result"""
    try:
        # Load result data from file
        with open(args.result_file, 'r') as f:
            result_data = yaml.safe_load(f)
            
        result = ExternalResult(args.task_id, args.handoff_id, args.output_dir)
        validated_result = result.submit_result(result_data)
        
        print("\nResult Submitted Successfully:")
        print("-" * 60)
        print(yaml.safe_dump(validated_result, sort_keys=False))
        print("-" * 60)
        
    except Exception as e:
        print(f"Error submitting result: {str(e)}")
        sys.exit(1)

def show_ledger(args: argparse.Namespace) -> None:
    """Show external agent ledger for a task"""
    try:
        ledger = ExternalAgentLedger(args.task_id, args.output_dir)
        ledger_data = ledger.get_ledger()
        
        print("\nExternal Agent Ledger:")
        print("-" * 60)
        print(yaml.safe_dump(ledger_data, sort_keys=False))
        print("-" * 60)
        
    except Exception as e:
        print(f"Error reading ledger: {str(e)}")
        sys.exit(1)

def main() -> None:
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(description="External Agent Handoff Management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # List agents subcommand
    list_parser = subparsers.add_parser("list", help="List configured external agents")
    
    # Create handoff subcommand
    handoff_parser = subparsers.add_parser("create-handoff", help="Create a new external agent handoff")
    handoff_parser.add_argument("--task-id", required=True, help="Task ID for the handoff")
    handoff_parser.add_argument("--agent-id", required=True, help="Agent ID to create handoff for")
    handoff_parser.add_argument("--title", required=True, help="Title of the handoff objective")
    handoff_parser.add_argument("--summary", required=True, help="Summary of the handoff objective")
    handoff_parser.add_argument("--output-dir", help="Directory to save handoff artifacts")
    
    # Submit result subcommand
    result_parser = subparsers.add_parser("submit-result", help="Submit an external agent result")
    result_parser.add_argument("--task-id", required=True, help="Task ID for the result")
    result_parser.add_argument("--handoff-id", required=True, help="Handoff ID for the result")
    result_parser.add_argument("--result-file", type=str, required=True, 
                             help="Path to YAML file containing the result data")
    result_parser.add_argument("--output-dir", help="Directory to save result artifacts")
    
    # Ledger subcommand
    ledger_parser = subparsers.add_parser("ledger", help="Show external agent ledger for a task")
    ledger_parser.add_argument("--task-id", required=True, help="Task ID to show ledger for")
    ledger_parser.add_argument("--output-dir", help="Directory containing the ledger")
    
    args = parser.parse_args()
    
    try:
        if args.command == "list":
            list_agents(args)
        elif args.command == "create-handoff":
            create_handoff(args)
        elif args.command == "submit-result":
            submit_result(args)
        elif args.command == "ledger":
            show_ledger(args)
        else:
            parser.print_help()
            sys.exit(1)
            
    except Exception as e:
        print(f"Error executing command: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()