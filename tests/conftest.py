import os
import sys

# Add project root to sys.path so tests can import app package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
