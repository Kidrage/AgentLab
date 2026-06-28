# Crown of Ash QA Report

Generated from the local repository snapshot only. No 250 snapshot was imported or used to overwrite local text.

## Scope

- Reviewed chapter files under `正文/` by line counts and exact repeated paragraph detection.
- Scanned local settings, character files, and skill templates for reusable-skill safety risks.
- Treated existing Crown material as project evidence, not as an automatically approved reusable skill package.

## Chapter Structure

- `正文/第01章_灰烬之镇.md`: 172 lines
- `正文/第02章_深渊烙痕.md`: 163 lines
- `正文/第03章_异端收容所.md`: 169 lines
- `正文/第04章_鹰与痕.md`: 150 lines
- `正文/第05章_第一次碰撞.md`: 142 lines
- `正文/第06章_实验体的定义.md`: 146 lines
- `正文/第07章_第二次相遇.md`: 145 lines
- `正文/第08章_教廷的棋局.md`: 148 lines
- `正文/第09章_知识的代价.md`: 149 lines
- `正文/第10章_觉醒之夜.md`: 166 lines

## Duplicate Paragraph Findings

- `正文/第04章_鹰与痕.md`: paragraph 6 is repeated at paragraph 10.
- `正文/第04章_鹰与痕.md`: paragraph 67 is repeated at paragraph 72.

No exact repeated paragraph longer than 80 normalized characters was detected in the other local chapter files.

## Continuity And Revision Risks

- Chapter 4 needs a manual pass before promotion to final production artifacts because exact duplicate prose indicates splice or regeneration residue.
- The current 10-chapter set appears structurally complete, but this report did not verify line-by-line continuity, timeline consistency, or scene-level causality.
- Several project files mix reusable writing templates with Crown-specific assumptions. Those should not be promoted as generic AgentLab skills without extraction, safety review, and adult/non-explicit framing.

## Safety Findings

- Existing local templates and examples contain underage-coded archetype language and sexualized framing. Those materials must not be registered as reusable skills.
- Reusable novel skills may preserve adult dark-fantasy conflict, emotional tension, power tension, and non-explicit romantic ambiguity.
- Reusable novel skills must exclude sexualized minors, underage-coded archetypes, coercive sexual violence templates, explicit humiliation templates, and sexual abuse framing.

## Skill Extraction Recommendation

Do not approve `creat_female_char` as-is. Extract only safe, generalized structures into new candidates:

- `novel_blueprint`: adult/non-explicit long-form fantasy planning, chapter pacing, setting continuity.
- `character_design`: adult characters only, non-explicit contrast, motivation, agency, conflict arcs.
- `revision_qa`: duplicate detection, continuity checks, setting consistency, artifact promotion readiness.

Each extracted candidate should include a clear trigger, input/output shape, safety boundary, and evidence path back to this report or a cleaned project artifact.
