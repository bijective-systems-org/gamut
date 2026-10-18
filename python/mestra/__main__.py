"""``python -m mestra``: the same command line as the ``mestra`` script."""
import sys

from mestra.cli import main

sys.exit(main())
