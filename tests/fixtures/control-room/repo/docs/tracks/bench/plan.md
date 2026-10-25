# Search bench: score search ideas offline

- State: active
- Coordinator: the widgets track session
- Done when: the search ships behind a switch and the owner has tried it
- Budget: two developer sessions, two review rounds each
- Updated: 2026-01-02

## Tasks and dependencies

| ID / task file | Deliverable | Depends on | Owned paths/interfaces | Assigned branch |
| --- | --- | --- | --- | --- |
| [A01: bench](tasks/A01-bench.md) | a bench that scores search ideas | this plan open | `tools/bench/` | `fiction/bench` |
| B01: stemming | a scored report | A01 open | `variants/stem.py` | unassigned |
| B02: synonyms | a scored report | B01 report | `variants/syn.py` | `fiction/synonyms` |

## Findings

Made-up numbers.

- **Stemming helps on short queries.** Plain words lose recipes with plurals; stemming
  finds them.
- **Synonyms cost more than they give.** They add noise to every query.

## Closure

Not started.
