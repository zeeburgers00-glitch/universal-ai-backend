# prompts/

Copy-paste prompts that make a coding AI actually finish the work.

| File | Kab use karo |
|---|---|
| `JARVIS_BUILD_PROMPT.md` | assistant/JARVIS backend banwana ho — 7 layers + honesty contract |
| `JARVIS_FULL_TOOLBELT_PROMPT.md` | us assistant ko **saare free tools** dena ho — 5 waves, 65 tools |
| `free_toolbelt.json` | machine-readable list: 65 free tools, install + test command + caveats |

## Order ye rakho

1. `JARVIS_BUILD_PROMPT.md` — pehle skeleton (memory, planner, chat, tests).
2. `free_toolbelt.json` + `JARVIS_FULL_TOOLBELT_PROMPT.md` — phir tools bharo, wave by wave.

Dono ek saath dene se AI 7 layers aur 65 tools ek hi turn me karne ki koshish karega aur
adhoora chhod dega.

## Sabse chhota version (chhote context window ke liye)

```
Give this assistant every tool in free_toolbelt.json, wave by wave: media -> docs ->
code/data -> ai -> web/ops.
Rules: (1) a tool exists only after its test passed AND it processed a real file;
(2) missing binary => {"error":"unavailable: <install>"} at call time, never fake data;
(3) registry with runtime availability checks + BM25 search; (4) decorator registration,
one file per category; (5) approval token for destructive/messaging tools;
(6) after each wave: pytest count, tool count, one real-run output, commit.
Report tools you could not install - acceptable. A fake tool is not.
Do wave 1 (media) now, then stop and report.
```
