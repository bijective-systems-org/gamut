"""``python -m gamut``: the same command line as the ``gamut`` script."""
import sys

from gamut.cli import main

sys.exit(main())
