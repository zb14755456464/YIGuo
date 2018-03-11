from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from functools import wraps
from django.db import transaction


class LoginRequiredMixin(object):
    """要求用户登录的功能补充逻辑"""
    @classmethod
    def as_view(cls, **initkwargs):
        view = super(LoginRequiredMixin, cls).as_view(**initkwargs)   # 实际上就是调用的django提供的类视图基类的as_view
        return login_required(view)


# 自定义的装饰器，用来检验登录状态，如果用户未登录，返回json数据
def login_required_json(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated():
            # 如果用户未登录， 返回json错误信息
            return JsonResponse({"code": 1, "message": "用户未登录"})
        else:
            # 如果用户已登录，则执行视图函数
            return view_func(request, *args, **kwargs)
    return wrapper


class LoginRequiredJsonMixin(object):
    """要求用户登录的功能补充逻辑, 使用自定义的login_required_json装饰器"""
    @classmethod
    def as_view(cls, **initkwargs):
        view = super(LoginRequiredJsonMixin, cls).as_view(**initkwargs)   # 实际上就是调用的django提供的类视图基类的as_view
        return login_required_json(view)


class TransactionAtomicMixin(object):
    """支持事务的操作"""
    @classmethod
    def as_view(cls, **initkwargs):
        view = super(TransactionAtomicMixin, cls).as_view(**initkwargs)
        return transaction.atomic(view)
