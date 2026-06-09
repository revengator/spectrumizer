"""Put the project dir (which contains the `spectrumizer` package) on sys.path so
`import spectrumizer` works when pytest is run from anywhere in the tree."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
