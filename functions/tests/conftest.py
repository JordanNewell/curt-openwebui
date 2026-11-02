import os
import sys

# Make the function module, the pipeline module, and the `pipelines.tests`
# fixture package importable when pytest runs from the repo root.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for path in (ROOT, os.path.join(ROOT, "pipelines"), os.path.join(ROOT, "functions")):
    if path not in sys.path:
        sys.path.insert(0, path)
