---
name: skill-creator
description: Create new skills, modify and improve existing skills, and measure skill performance. Use when users want to create a skill from scratch, edit, or optimize an existing skill, run evals to test a skill, benchmark skill performance with variance analysis, or optimize a skill's description for better triggering accuracy.
---

# Skill Creator

A skill for creating new skills and iteratively improving them.

At a high level, the process of creating a skill goes like this:

- Decide what you want the skill to do and roughly how it should do it
- Write a draft of the skill
- Create a few test prompts and run claude-with-access-to-the-skill on them
- Help the user evaluate the results both qualitatively and quantitatively
- Rewrite the skill based on feedback from the user's evaluation of the results
- Repeat until you're satisfied
- Expand the test set and try again at larger scale

Your job when using this skill is to figure out where the user is in this process and then jump in and help them progress through these stages.

## Creating a skill

### Capture Intent
Start by understanding the user's intent. The current conversation might already contain a workflow the user wants to capture (e.g., they say "turn this into a skill"). If so, extract answers from the conversation history first.

### Write the SKILL.md
Based on the user interview, fill in these components:
- **name**: Skill identifier
- **description**: When to trigger, what it does. This is the primary triggering mechanism.
- **compatibility**: Required tools, dependencies (optional, rarely needed)
- **the rest of the skill** with Markdown instructions

### Skill Writing Guide
Skills use a three-level loading system:
1. **Metadata** (name + description) - Always in context
2. **SKILL.md body** - In context whenever skill triggers
3. **Bundled resources** - As needed

### Running and evaluating test cases
For each test case, spawn two subagents — one with the skill, one without — and compare results.

### The iteration loop
After improving the skill:
1. Apply your improvements to the skill
2. Rerun all test cases into a new iteration directory
3. Wait for the user to review
4. Read the new feedback, improve again, repeat

## Safety
- No commands are executed by AgentLab during import.
- The imported source is stored as a source snapshot for review.
- Promotion follows the normal approval and fake validation lifecycle.