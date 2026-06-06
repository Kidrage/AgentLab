I need to inspect the run directory and project memory to determine what artifacts actually exist before writing the verification report.

<tool_call>
<function=shell>
<parameter=command>
ls -la /Users/saintpeter/Desktop/AgentLab/projects/AO-SpatialAuthoring-Modular/runs/task_0002_longterm-knowledgebase-research/ 2>/dev/null || echo "DIR_NOT_FOUND"
</parameter>
</function>
</tool_call>