# Epic Chronicle Project Fact State

This note records the implementation target for ultra-long epic chronology projects,
using `projects/Crown_of_Ash` as the first concrete fit check.

## Crown Of Ash Fit Check

Current Crown material is larger than an ordinary novel workflow. The latest local
architecture includes:

- cosmic ontology: Solar Light, Abyssal Shadow, Ash, Arcane, Entropy, Cycle.
- chronology: ancient eras, Ash Dynasty, Church rise, A.C. main trilogy.
- branch timelines: Frozen Light, Abyssal Rust, Iron Reign.
- continuity anchors: character bible, relationship map, magic cost rules, volume and chapter route.
- hard invariants: no resurrection, no free power, no real prophecy, memory loss changes identity.

The generic project fact state system is viable for this task after adding the
`epic_chronicle_project` preset. The ordinary `longform_text_project` preset is
too shallow by itself because it only tracks characters, locations, items,
relationships, factions, and timeline events. Crown also needs branch timelines,
cosmic forces, power stages, covenants, mystery threads, and volume/chapter arcs.

## Required State Machine Shape

The brain layer should compile Crown-style requests into `epic_chronicle_project`
when the user goal contains epic, chronicle, saga, worldbuilding, `史诗`, `编年史`,
or `世界观`.

```yaml
selected_preset: epic_chronicle_project
dimensions:
  chronology:
    - era
    - timeline_event
    - timeline_branch
    - volume_arc
    - chapter_arc
  ontology:
    - cosmic_force
    - magic_system
    - power_stage
    - covenant
  continuity:
    - character
    - faction
    - location
    - item
    - relationship
    - mystery_thread
status_sequences:
  power_stage:
    - seeded
    - awakened
    - erosion
    - burning
    - abyssal
    - ashen
    - crowned
    - spent
  mystery_thread:
    - seeded
    - active
    - revealed
    - resolved
    - deferred
  chapter_arc:
    - planned
    - drafting
    - reviewed
    - accepted
    - archived
invariants:
  - dead_character_requires_restore_event
  - timeline_echo_requires_source_branch
  - covenant_requires_named_parties
```

## Crown Initial Fact State Sketch

This is the expected durable fact state representation for a Crown project brain.
It is not stored as fixed Crown-specific code; workers should produce these facts
through `state_transition_proposal.yml` during planning and drafting phases.

```yaml
entities:
  cosmic_force:
    solar_light:
      status: active
      facts:
        role: order, preservation, extreme stasis
    abyssal_shadow:
      status: active
      facts:
        role: possibility, decay, erased timeline repository
    ash:
      status: active
      facts:
        role: neutral memory-bearing remainder of light and abyss collision
  era:
    bc_10000_ash_coalescence:
      status: active
      facts:
        order: -10000
        event: First Crown lands on Aezes
    ac_0_ash_valley:
      status: active
      facts:
        order: 0
        event: Kaine brand awakens
  timeline_branch:
    frozen_light:
      status: active
      facts:
        divergence: Kaine captured in chapter 01
        terminal_state: pure static order
    abyssal_rust:
      status: active
      facts:
        divergence: abyss mishandled in chapter 03
        terminal_state: world dissolves into rust sea
    iron_reign:
      status: active
      facts:
        divergence: Kaine captured by Ironmask in chapter 11
        terminal_state: mechanized authoritarian empire
  character:
    kaine_ashford:
      status: active
      facts:
        arc: revenger to new watcher
        power_stage: awakened
    leah:
      status: active
      facts:
        role: ash brand residual will
        boundary: no sexualized framing
  mystery_thread:
    dragonbone_islands_grey_light:
      status: seeded
      facts:
        intended_resolution: sequel hook
```

## Operational Rule

For each batch of chapters or worldbuilding updates, the executor must submit a
`state_transition_proposal.yml` if it changes durable facts. Phase acceptance then
validates and applies the transition to `project_fact_events.jsonl` and rebuilds
`project_fact_snapshot.yml`. This moves the project away from relying on raw
previous-context reading and toward an append-only, inspectable chronology.
