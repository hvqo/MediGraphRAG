# Historical Python code

This directory preserves earlier implementations and experiments. It is not part
of the maintained backend import path. These modules may require optional legacy
dependencies and old input data. They have not been certified as production jobs.

- `experiments/`: all code cells recovered from the original three notebooks.
  Code is retained inside `historical_pipeline()` so imports never execute model
  calls, database writes or old unbounded loops. Running a file prints a pointer
  to the maintained CLI instead of automatically executing the old experiment.
- `prototypes/`: original Python prototypes previously inside `docx/process`.
- `utils/`, `agent/`: original LangChain and MetaGPT utilities.

Use `python -m backend.app.cli --help` for maintained import, search, index and
server commands. Notebook markdown and the SHA256 cell manifest are under
`docs/legacy`. Validate complete source recovery using
`python scripts/convert_legacy_notebooks.py`. Only two wildcard imports were
expanded to explicit imports to make the recovered functions valid Python.

Original notebook outputs remain available in Git history at the revision
recorded in the manifest; they are not copied into application source files.
