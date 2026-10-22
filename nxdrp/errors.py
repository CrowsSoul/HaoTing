# -*- coding: utf-8 -*-
"""框架统一异常。分层：契约错误 -> 数据问题；适配器错误 -> 环境/模型问题。"""


class DrpError(Exception):
    """所有框架异常的基类。"""


class ContractError(DrpError):
    """数据不符合模型契约（ModelBundle / RuleSet / Finding）。"""

    def __init__(self, message, problems=None):
        self.problems = list(problems or [])
        if self.problems:
            message = message + "\n  - " + "\n  - ".join(self.problems)
        super().__init__(message)


class AdapterError(DrpError):
    """模型来源不可用（NX 未安装、License 占用、journal 失败等）。"""


class NxNotAvailableError(AdapterError):
    """本机找不到可用的 NX / run_journal。"""


class JournalError(AdapterError):
    """NX 批处理 journal 执行失败，携带 NX 侧回传的诊断信息。"""

    def __init__(self, message, diagnostics=None):
        self.diagnostics = diagnostics or {}
        super().__init__(message)


class CheckerError(DrpError):
    """单个 checker 执行失败。管线会捕获它并继续跑其它 checker。"""
