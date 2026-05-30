"""
用法：
    from utils import logger
    logger.session.trace_id = trace_id
    logger.info("Request Params: ...")
    logger.error("Internal Error!")
"""

import logging
import os
import sys
from logging import LoggerAdapter


__all__ = []

levelname = os.environ.get('LOG_LEVEL', "INFO")
_LEVEL_SET = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
_LOGGING_METHOD = ["info", "warning", "error", "debug"]


class _Formatter(logging.Formatter):
    def format(self, record):
        msg = "%(message)s"
        pattern = "%(asctime)s.%(msecs)03d %(levelname)s [pid-%(process)d] @%(filename)s:%(lineno)d"
        fmt = pattern + " " + msg
        if hasattr(self, "_style"):
            self._style._fmt = fmt
        self._fmt = fmt
        return super(_Formatter, self).format(record)


class _SessionLoggerAdapter(LoggerAdapter):
    """将 trace_id 自动注入到每一条日志前缀"""

    def process(self, msg, kwargs):
        if 'session' not in self.extra or self.extra['session'] is None:
            return msg, kwargs
        session = self.extra['session']
        if hasattr(session, 'trace_id') and session.trace_id:
            msg = '[{}] {}'.format(session.trace_id, msg)
        if 'extra' not in kwargs:
            kwargs["extra"] = self.extra
        else:
            kwargs['extra'].update(self.extra)
        return super().process(msg, kwargs)


def Singleton(cls):
    """单例装饰器"""
    _instance = {}

    def _singleton(*args, **kargs):
        if cls not in _instance:
            _instance[cls] = cls(*args, **kargs)
        return _instance[cls]

    return _singleton


import contextvars

# 声明一个上下文变量，默认值为 "unknown"
_trace_id_var = contextvars.ContextVar("trace_id", default="unknown")

class Session:
    """包装类，对外保持原本的接口，底层读写转移到 contextvars"""
    @property
    def trace_id(self):
        return _trace_id_var.get()

    @trace_id.setter
    def trace_id(self, value):
        _trace_id_var.set(value)


def _getlogger():
    package_name = "cardle"
    _logger = logging.getLogger(package_name)
    _logger.propagate = False
    _logger.setLevel(_LEVEL_SET.get(levelname, 20))

    # Windows 下需要 utf-8 encoding 防止中文乱码
    handler = logging.StreamHandler(sys.stdout)
    if hasattr(handler.stream, 'reconfigure'):
        try:
            handler.stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    handler.setFormatter(_Formatter(datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(handler)
    return _logger


# ── 全局对象 ──
session = Session()

_logger = _getlogger()
_logger = _SessionLoggerAdapter(_logger, {'session': session})

# 将方法导出到模块顶层，使 logger.info(...) 可以直接调用
for _func in _LOGGING_METHOD:
    locals()[_func] = getattr(_logger, _func)
    __all__.append(_func)
