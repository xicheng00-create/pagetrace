import os
import sys

sys.path.insert(0, os.environ.get("VIDEOKIT_HOME", os.path.expanduser("~/VideoKit")))
from videokit.pipeline import main

sys.exit(main())
