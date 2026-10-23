"""M8 报告与知识库，仅消费检查结果。"""
__version__ = "1.1.0"
CHECKERS = []

def generate_report(*args, **kwargs):
    from .service import generate_report as generate
    return generate(*args, **kwargs)
