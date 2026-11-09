"""``python -m wxpush`` 等价于 ``wxpush.cli``。"""

import sys

from .cli import main

sys.exit(main())
