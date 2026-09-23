"""Dev helper: print every registered route (not part of the app)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402

for rule in sorted(app_module.app.url_map.iter_rules(), key=lambda r: r.rule):
    methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
    print(",".join(methods).ljust(12), rule.rule)
