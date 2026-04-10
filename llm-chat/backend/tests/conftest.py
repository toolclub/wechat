"""
测试配置 — pytest fixtures 和标记注册
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "unit: 纯单元测试（无 DB/Redis）")
    config.addinivalue_line("markers", "integration: 集成测试（需 DB/Redis）")
    config.addinivalue_line("markers", "smoke: 冒烟拨测（端到端）")
