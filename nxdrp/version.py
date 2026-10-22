# -*- coding: utf-8 -*-
"""版本号。契约版本与框架版本分开，契约破坏性变更时同步升级 SCHEMA_VERSION。"""

__version__ = "0.1.0"
SCHEMA_VERSION = "1.0.0"

#: 本框架验证过的 NX 版本。其它版本可运行，但 nxdrp.tools.doctor 会提示风险。
TESTED_NX_VERSIONS = ("2606",)
