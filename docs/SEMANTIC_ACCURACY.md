# Curated semantic accuracy checks

[Documentation home](README.md) · [Capability matrix](CAPABILITIES.md)

The fixtures in `tests/semantic_cases.json` are manually authored source examples for
import and assignment aliases, inheritance, decorators, callback parameters, callback
factories, direct calls, and conditional definitions. They are parsed as text and never
imported or executed. Expectations are independent of the analyzer's output.

Run:

```bash
python test_semantic_accuracy.py --report artifacts/semantic-accuracy.json
```

The same corpus runs under `python -m unittest discover -v`. CI retains the standalone
JSON report. Every annotated call checks target bounds, allowed certainty labels, and
exact source evidence. An incorrect **supported** relationship fails the gate separately
from other mismatches. Unknown targets are measured, even where the expectation allows
them conservatively.

The initial 14-case run reported zero incorrect supported relationships, seven unknown
calls, and three supported resolutions among four annotated direct targets. The local
assignment alias remained unknown in that historical run. The expanded corpus now
includes common object-oriented calls, lexical binding, and execution-context cases.
Its current counts come from the generated JSON report, not the earlier run. This small
curated corpus is not a general accuracy percentage, an execution trace, or a complete
semantic oracle. Inheritance and callback examples allow uncertainty; passing them does
not mean those dispatch mechanisms are fully resolved.

When adding a case, write the source expectation and its rationale before inspecting
analyzer output. Do not relax certainty or target bounds merely to make a test pass.
Use the pinned public-repository corpus alongside these focused examples.
