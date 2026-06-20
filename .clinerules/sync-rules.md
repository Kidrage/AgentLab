# Dual-End Collaboration and Sync Protocol (双端协作与同步协议)
Local development on this Mac takes priority. The remote SSH workspace on TrueNAS (`<PRIVATE_RELAY_HOST>`) acts as the central resource relay hub, and the cloud server (`<PRIVATE_CLOUD_RUNTIME>`) acts as the run/deployment target.

*   **Local Mac -> TrueNAS (`<PRIVATE_RELAY_HOST>`)**: Push local changes to configs, skills, memory snapshots using:
    `./agentlab.sh truenas-sync --execute`
    Or manual rsync:
    `rsync -avz -e "ssh -p <PRIVATE_RELAY_SSH_PORT>" --exclude '__pycache__' --exclude '.pytest_cache' /path/to/AgentLab/ agentlab@<PRIVATE_RELAY_HOST>:/mnt/hdd2/AgentLab_WorkSpace/`
*   **TrueNAS (`<PRIVATE_RELAY_HOST>`) -> Cloud Runtime (`<PRIVATE_CLOUD_RUNTIME>`)**: Remote agents on `<PRIVATE_CLOUD_RUNTIME>` pull workspace/skills/MCP updates from `<PRIVATE_RELAY_HOST>` using:
    `ssh admin@<PRIVATE_CLOUD_RUNTIME> "rsync -avz --exclude '__pycache__' --exclude '.pytest_cache' truenas:/mnt/hdd2/AgentLab_WorkSpace/ /home/admin/AgentLab/"`
