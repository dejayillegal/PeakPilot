import os
import sys

# Ensure project root is on path so that `import app` works when tests are run
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
