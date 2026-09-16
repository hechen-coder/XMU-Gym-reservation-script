# -*- coding: utf-8 -*-
import sys
import types
if 'cv2' not in sys.modules:
    sys.modules['cv2'] = types.ModuleType('cv2')
