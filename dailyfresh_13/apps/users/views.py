from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.views.generic import View
import re
from django.core.urlresolvers import reverse
from users.models import User
from django import db
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from django.conf import settings
from itsdangerous import SignatureExpired
from celery_tasks.tasks import send_active_email
from django.contrib.auth import authenticate, login, logout
from utils.views import LoginRequiredMixin
from users.models import Address
from django_redis import get_redis_connection
from users import constants
from goods.models import GoodsSKU
import json

# Create your views here.

# def register(request):
#     """注册"""
#     # 使用get方式访问 获取页面
#     if request.method == "GET":
#         return render(request, "register.html")
#     else:
#         # post请求方式
#         return HttpResponse("post请求方式")


class RegisterView(View):
    """注册"""
    def get(self, request):
        """对应get请求方式，提供注册页面"""
        return render(request, "register.html", )

    def post(self, request):
        """对应post请求方式，接收处理用户的注册数据"""
        # 接收传入的参数
        user_name = request.POST.get("user_name")
        password = request.POST.get("pwd")
        email = request.POST.get("email")
        allow = request.POST.get("allow")

        # 检验参数的正确性
        if not all([user_name, password, email]):
            # 重定向到注册页面
            return redirect(reverse("users:register"))

        if not re.match(r"^[a-z0-9][\w\.\-]*@[a-z0-9\-]+(\.[a-z]{2,5}){1,2}$", email):
            # 返回错误信息
            return render(request, "register.html", {"errmsg": "邮箱格式不正确"})

        if allow != "on":
            return render(request, "register.html", {"errmsg": "请接收注册协议！"})

        # 进行业务逻辑处理，将数据保存到数据库
        # 注意用户的密码要加密，
        try:
            # django的AbstractUser基类提供的创建用户的方法
            user = User.objects.create_user(user_name, email, password)
        except db.IntegrityError:
            # 如果用户名已存在，则抛出此异常信息
            return render(request, "register.html", {"errmsg": "用户名已存在！"})

        # 将用户的激活状态设置为假
        user.is_active = False
        user.save()

        # 为用户生成激活口令
        token = user.generate_active_token()

        # 使用celery异步发送邮件
        send_active_email.delay(user_name, email, token)

        # 将结果返回给前端
        return redirect(reverse("goods:index"))


class ActiveView(View):
    """激活"""
    def get(self, request, token):
        """

        :param request:
        :param token: token是用户携带的口令，唯一标识用户
        :return:
        """
        # 解析口令token，获取用户身份
        # 构建序列化器
        s = Serializer(settings.SECRET_KEY)
        try:
            data = s.loads(token)
        except SignatureExpired:
            # 表示token过期
            return HttpResponse("链接已过期！")
        # 表示token未过期，
        user_id = data.get("confirm")

        # 查询用户的数据
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            # 用户不存在
            return HttpResponse("用户不存在！")
        # 设置用户的激活状态
        user.is_active = True
        user.save()

        # 返回处理结果
        # return HttpResponse("进入到登录页面")
        return redirect(reverse("users:login"))


class LoginView(View):
    """登录"""
    def get(self, request):
        """提供登录页面"""
        return render(request, "login.html")

    def post(self, request):
        """处理登录的数据"""
        # 获取参数
        user_name = request.POST.get("username")
        password = request.POST.get("pwd")
        remembered = request.POST.get("remembered")  # 记住用户名的参数

        # 参数校验
        if not all([user_name, password]):
            # 参数不完整
            return render(request, "login.html")

        # 登录业务逻辑处理
        # try:
        #     password = sha256(password)
        #     User.objects.get(username=user_name, password=password)
        # except User.DoesNotExist:
        #     return HttpResponse("用户名或密码错误")

        # 使用django的认证系统进行用户密码的校验
        user = authenticate(username=user_name, password=password)
        if user is None:
            # 用户的登录信息有误
            return render(request, "login.html", {"errmsg": "用户名或密码错误！"})

        # 判断用户的激活状态
        if user.is_active is False:
            return render(request, "login.html", {"errmsg": "用户尚未激活！"})

        # 保存用户的登录状态
        # 使用django的login函数保存用户的session数据
        login(request, user)
        # 根据用户勾选的记住用户名选项，设置session数据的有效期（django帮助我们完成cookie有效期的设置）
        if remembered != "on":
            # 表示用户没有勾选
            request.session.set_expiry(0)  # 设置为临时会话
        else:
            # 表示用户勾选
            request.session.set_expiry(None)  # 采用django的默认设置有效期

        # 合并用户的cookie购物车和redis购物车
        # 获取cookie中的购物车数据
        cart_json = request.COOKIES.get("cart")
        if cart_json is not None:
            cart_cookie = json.loads(cart_json)
        else:
            cart_cookie = {}

        # 获取redis中的购物车数据
        redis_conn = get_redis_connection("default")
        cart_redis = redis_conn.hgetall("cart_%s" % user.id)

        # 合并,
        # cart_redis.update(cart_cookie)
        # 数量求和
        for sku_id, count in cart_cookie.items():
            # sku_id 从cookie取出时str类型，redis中是bytes类型
            sku_id = sku_id.encode()
            if sku_id in cart_redis:
                orign_count = cart_redis[sku_id]
                count += int(orign_count)

            cart_redis[sku_id] = count

        # 将合并的结果保存到redis中
        if cart_redis:
            redis_conn.hmset("cart_%s" % user.id, cart_redis)

        # 清除cookie中购物车数据
        # 先构建response

        # 登录成功，
        # 判断页面url中是否有next参数，
        next = request.GET.get("next")
        # 如果有，则跳转到next的url
        if next:
            response = redirect(next)
        else:
            # 如果没有，跳转到主页
            response = redirect(reverse("goods:index"))

        # 通过response清除cookie
        response.delete_cookie("cart")

        return response


class LogoutView(View):
    """退出"""
    def get(self, request):
        # 使用django的认证系统提供的logout函数，清除session数据
        logout(request)
        # 跳转到主页
        return redirect(reverse("goods:index"))


class AddressView(LoginRequiredMixin, View):
    """用户地址"""
    def get(self, request):
        """提供用户地址页面"""
        user = request.user  #登录的用户对象

        # 获取用户的地址信息,按照创建时间选择最新的一条
        try:
            address = user.address_set.latest("create_time")
        except Address.DoesNotExist:
            address = None

        context = {
            # "user": user,  # 这个数据可以不用传，在的django中可以直接使用
            "address": address
        }

        # 渲染模板
        return render(request, "user_center_site.html", context)


    def post(self, request):
        """维护地址信息"""
        user = request.user

        recv_name = request.POST.get("recv_name")
        addr = request.POST.get("addr")
        zip_code = request.POST.get("zip_code")
        recv_mobile = request.POST.get("recv_mobile")

        if all([recv_name, addr, zip_code, recv_mobile]):
            # address = Address(
            #     user=user,
            #     receiver_name=recv_name,
            #     detail_addr=addr,
            #     zip_code=zip_code,
            #     receiver_mobile=recv_mobile
            # )
            # address.save()
            Address.objects.create(
                user=user,
                receiver_name=recv_name,
                detail_addr=addr,
                zip_code=zip_code,
                receiver_mobile=recv_mobile
            )
        return redirect(reverse("users:address"))


class UserInfoView(LoginRequiredMixin, View):
    """用户信息页面"""
    def get(self, request):
        # 获取用户的地址信息
        user = request.user
        # 获取用户的地址信息,按照创建时间选择最新的一条
        try:
            address = user.address_set.latest("create_time")
        except Address.DoesNotExist:
            address = None

        # 获取用户的浏览历史记录
        # 拿到一个redis连接对象
        redis_conn = get_redis_connection("default")
        # 存在redis中的历史数据是哈希类型
        # conn.lrange(“history_1”, 0, 4)
        sku_ids = redis_conn.lrange("history_%s" % user.id, 0, constants.USER_HISTORY_NUM-1)

        # 从数据库中，按照sku id查询商品的信息

        # 一次性查出所有数据，顺序变了，所以不采纳
        # select * from tbl where id in ()
        # skus = GoodsSKU.objects.filter(id__in=sku_ids)

        skus = []
        for sku_id in sku_ids:
            sku = GoodsSKU.objects.get(id=sku_id)
            skus.append(sku)

        context = {
            # "user": user,  # 这个数据可以不用传，在的django中可以直接使用
            "skus": skus,
            "address": address,
        }

        return render(request, "user_center_info.html", context)














