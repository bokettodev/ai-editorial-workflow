# Evidence-backed editorial brief

This local workflow turns the public homepage into a short, reviewable editorial brief. It fetches one allowlisted page, strips scripts and styles, asks one read-only Codex session to propose ideas, checks every literal citation against the page, then asks a separate session to challenge support. A second deterministic citation check guards the handoff. Output is written locally; nothing is sent or published by the workflow.

## Run

Requires Python 3.10+, an authenticated `codex` CLI on PATH, and network access to the fixed public source.

```sh
python workflow.py --out out
python -m unittest -v
```

The brief in `out/brief.md` is a draft for a human editor, not a factual or publishing guarantee. The language model can still draw a weak inference from a valid quote, so the reviewer should inspect source and wording. The process fails closed on unparseable output, missing evidence, model failure, oversized input, or redirects away from the source. No provider credentials are embedded in the repository.
