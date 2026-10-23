"""使团队统一测试命令自动包含 M8 回归测试，不改其他模块。"""
from nxdrp.checkers.m8_report.test_m8 import NormalizationTests, ArchiveTests, AcceptanceTests
