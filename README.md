# Evidence-backed editorial brief for prommer.net

A small two-agent workflow that reads the public prommer.net homepage and drafts article ideas an editor can check quickly. Every idea cites a passage that code has matched verbatim against the fetched page, and a second, separate agent session has said keep or drop and why. Nothing is published or sent; the output is a draft for a human editor.

## Pipeline

| Step | Run by | Output | Handed to the next step |
|---|---|---|---|
| 1. Fetch | `urllib`; one allowlisted HTTPS host, checked on every redirect hop; 2 MB cap | HTML and its sha256 | HTML |
| 2. Extract | `html.parser`; drops script, style, svg and noscript; 24,000-character cap, recorded if hit | `source.txt` | page text inside the planner prompt |
| 3. Plan | Codex session 1 (`codex exec`, ephemeral, JSON schema) | up to 5 ideas: title, angle, verbatim evidence | raw JSON |
| 4. Evidence gate | deterministic code | accepted ideas with ids `i1…`, rejected ideas with reasons | accepted ideas only, plus one planted control idea |
| 5. Review | Codex session 2, separate and ephemeral | one keep/drop decision with a reason per id, and an optional verbatim passage showing existing coverage | raw JSON |
| 6. Review contract and render | deterministic code | `brief.md`, `reviewed.json`, `run.json` | the human editor |

What is enforced in code rather than by prompt:

- Evidence must be 20–300 characters and appear verbatim (after whitespace normalisation) in the fetched text. A bad idea is rejected and recorded without discarding the others. Titles, angles and reviewer reasons may not contain links or markup.
- The reviewer can only keep or drop the ids it was given. Unknown, repeated or missing ids, or an "already covered" passage that is not on the page, stop the run. Its text never replaces the planner's.
- Each review includes a planted control idea: a real quote from the page paired with an invented cost reduction. If the reviewer keeps it, none of its keep decisions are trusted and the run stops. The control never reaches the brief.
- Each agent session runs with `--ignore-user-config`, so no MCP servers or other settings from the user's `config.toml` are loaded. Codex's default-on tool, plugin and hook features are switched off where the installed CLI knows them. The session is rejected if its `--json` event stream contains any item other than reasoning, plan or error notices and the final message.
- The prompt is passed to Codex as UTF-8 bytes. A failed run still writes `run.json` with the stage and error, and it removes any older brief from the output directory.

What still depends on the model: whether an angle is a fair reading of its quote, and whether an idea is worth writing. The reviewer's reason is printed under each idea so the editor can disagree with it.

## Run

Requires Python 3.10+, an authenticated `codex` CLI and network access to prommer.net. Tested on Windows 11 with Python 3.13.5 and codex-cli 0.164.0.

```sh
python workflow.py                          # writes runs/<UTC run id>/
python workflow.py --verify runs/<run id>   # offline replay of a saved run
python -m unittest -v                       # offline: fake agent, no network, no Codex
```

## Run record

Each `runs/<id>/` directory contains these files:

- `source.txt`: the page text both agents saw.
- `run.json`: source hashes, CLI version, disabled features, per-step duration and token usage, the raw agent answers, gate rejections, the control idea and every reviewer decision. It is written for failed runs too.
- `reviewed.json` and `brief.md`.

`--verify` recomputes the source hash and re-runs the evidence gate, control idea and review contract on the recorded agent answers. It then checks that `reviewed.json` and `brief.md` are identical, so a run can be audited without network or model access. It also reports whether the run was produced by the current `workflow.py`.

A local run of this version proposed 3 ideas; the reviewer kept all 3 and dropped the control. Planner and reviewer took 24 s and 16 s, with about 20k input and 250 output tokens each. Full run records and source snapshots remain local; generate your own run to use offline replay. `out/brief.md` is the output of the first published version, which kept no run record.

## Failure log

- The first live run fetched and extracted the page, but the planner never started. Python encoded the stdin prompt with the Windows code page and raised `UnicodeEncodeError` on a character from the page. The fix was explicit UTF-8 at the subprocess boundary.
- A later fake-agent test showed that text mode on Windows still rewrote every `\n` in the prompt as `\r\n`. The boundary now passes bytes, and `test_prompt_reaches_agent_as_exact_utf8` checks the bytes the agent receives.

## Changes since the first published version (2026-10-29)

The first published version is available at commit `10538da7af79fca229fbbc1635345361b3d1fc00`. The changes below were made after that submission.

- The reviewer returns keep/drop decisions per id instead of a rewritten list, and code applies them. A planted control idea checks that the reviewer is actually checking support.
- One bad quote now rejects that idea, not the whole run. Quotes have an upper length limit, and links and markup are rejected.
- Agent sessions run without user config or tool features, and their event streams are checked.
- Each run writes a record, and `--verify` replays it offline. Redirects are checked on every hop.
- The tests grew from 4 to 16 and now cover the subprocess boundary, the review contract, the control idea, tool-use detection, replay and tamper detection.

## Limitations

- One page is the only source, so ideas can only extend what the homepage says. The model chooses the ideas, and they vary from run to run.
- The control idea is one easy case per run. It catches a reviewer that approves everything, but it does not measure how often the reviewer misses subtler unsupported angles. That needs a labelled set of good and bad ideas.
- Both roles use the same default model, so their errors can be correlated. "Already covered" detection relies on the reviewer quoting the page; nothing checks it against the site's full archive.
- Tool use is blocked by CLI features and detected from the event stream. This is not an OS-level sandbox for the Codex process.
