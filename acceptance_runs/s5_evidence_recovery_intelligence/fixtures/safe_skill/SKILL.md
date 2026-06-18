---
id: s5-safe-local-evidence-demo
name: S5 Safe Local Evidence Demo
version: 1.0.0
license: MIT
capabilities:
  - local_evidence_demo
source:
  type: local
risk:
  level: low
permissions:
  shell: false
  network: false
  filesystem:
    read: true
    write: false
---

# S5 Safe Local Evidence Demo

This package is used only to produce S4 trust reports for the S5 acceptance
smoke. It is metadata-only and has no runtime entrypoint.
