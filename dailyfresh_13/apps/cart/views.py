from django.shortcuts import render
from django.views.generic import View
from django.http import JsonResponse
from goods.models import GoodsSKU
from django_redis import get_redis_connection
import json

# Create your views here.


# /cart/add

class AddCartView(View):
    """添加购物车"""
    def post(self, request):
        # # 判断用户是否登录
        # if not request.user.is_authenticated():
        #     # 表示用户未登录
        #     return JsonResponse({"code": 1, "message": "用户未登录"})

        # sku_id 商品id
        # count 商品数量
        # 接受参数
        sku_id = request.POST.get("sku_id")
        count = request.POST.get("count")

        # 校验参数
        if not all([sku_id, count]):
            return JsonResponse({"code": 2, "message": "参数不完整"})

        # 判断商品存在与否
        try:
            sku = GoodsSKU.objects.get(id=sku_id)
        except GoodsSKU.DoesNotExist:
            # 表示商品不存在
            return JsonResponse({"code": 3, "message": "商品不存在"})

        # 判断用户请求的count是不是整数
        try:
            count = int(count)
        except Exception:
            # 数量不是整数
            return JsonResponse({"code": 4, "message": "参数错误"})

        # 判断数量有没有超过库存
        if count > sku.stock:
            return JsonResponse({"code": 5, "message": "库存不足"})

        # 业务逻辑处理，
        if request.user.is_authenticated():
            user_id = request.user.id
            # 如果用户登录，将数据保存到redis中
            # "cart_user_id": {"sku_1": 10, "sku_2": 20}
            redis_conn = get_redis_connection("default")

            # 先从redis中尝试获取用户原有购物车中相同商品的信息
            user_id = request.user.id
            origin_count = redis_conn.hget("cart_%s" % user_id, sku_id)

            # 如果redis中不存在，则直接将数据保存到redis的购物车中
            # 如果redis中原本包含了这个商品的数量信息， 进行数量累加，在保存到redis中
            if origin_count is not None:
                count += int(origin_count)

            redis_conn.hset("cart_%s" % user_id, sku_id, count)

            # 计算购物车中最新的总数
            cart_num = 0
            cart = redis_conn.hgetall("cart_%s" % user_id)
            # {"sku_id": "10", "sku_id": "11"}
            for val in cart.values():
                cart_num += int(val)
            # 通过返回json数据，告知前端处理的结果
            return JsonResponse({"code": 0, "message": "添加购物车成功", "cart_num": cart_num})
        else:
            # 如果用户未登录，则将数据保存到cookie中
            # 先获取用户的cookie中的购物车数据
            cart_json = request.COOKIES.get("cart")
            if cart_json is not None:
                # 用户的cookie中有购物车数据
                cart = json.loads(cart_json)   # 将json字符串转换为字典
            else:
                # 用户的cookie中原本没有购物车数据
                cart = {}

            # {"sku_id": 10, "sku_id": 11}
            if sku_id in cart:  # 判断键是否存在
                # 如果购物车数据中包含了这个商品，则进行数量求和
                origin_count = cart[sku_id]  # 原有的数量
                count += origin_count

            # 在购物车的字典数据中保存这个商品的信息
            cart[sku_id] = count

            # 再最新的商品数量添加到cookie的购物车数据中
            new_cart_json = json.dumps(cart)  # 将字典转换为json字符串

            # 统计购物车中的商品总数
            cart_num = 0
            for val in cart.values():
                cart_num += val

            # 构造返回的JsonResponse对象，再设置cookie
            response = JsonResponse({"code": 0, "message": "添加购物车成功", "cart_num": cart_num})
            response.set_cookie("cart", new_cart_json)
            return response


class CartInfoView(View):
    """用户的购物车页面"""
    def get(self, request):
        """提供页面"""
        # 获取数据
        if not request.user.is_authenticated():
            # 如果用户未登录，从cookie中读取购物车数据
            cart_json = request.COOKIES.get("cart")
            # 判断用户的cookie中是否存在cart的购物车数据
            if cart_json is not None:
                cart = json.loads(cart_json)
                # {"sku_id": 10}
            else:
                cart = {}
        else:
            # 如果用户已登录，从redis中读取购物车数据
            redis_conn = get_redis_connection("default")
            user_id = request.user.id
            cart = redis_conn.hgetall("cart_%s" % user_id)

        # 遍历cart字典购物车，从mysql数据中查询商品信息
        skus = []
        total_count = 0  # 商品总数
        total_amount = 0  # 商品总金额
        for sku_id, count in cart.items():
            try:
                sku = GoodsSKU.objects.get(id=sku_id)
            except GoodsSKU.DoesNotExist:
                # 商品不存在
                continue
            # 计算商品的金额
            count = int(count)
            amount = sku.price * count    # price字段是DecimalField, 在python中是Decimal数据类型
            sku.amount = amount
            sku.count = count
            skus.append(sku)

            total_count += count
            total_amount += amount

        # 处理模板
        context = {
            "skus": skus,
            "total_count": total_count,
            "total_amount": total_amount
        }

        return render(request, "cart.html", context)


class UpdateCartView(View):
    """更新购物车数据"""
    def post(self, request):
        # 获取数据
        sku_id = request.POST.get("sku_id")  # 商品id
        count = request.POST.get("count")  # 修改之后的数量

        # 检查数据
        # 判断商品是否存在
        try:
            sku = GoodsSKU.objects.get(id=sku_id)
        except GoodsSKU.DoesNotExist:
            return JsonResponse({"code": 1, "message": "商品不存在"})

        # count是否是整数
        try:
            count = int(count)
        except Exception:
            return JsonResponse({"code": 2, "message": "数量参数有问题"})

        # 判断库存
        if count > sku.stock:
            return JsonResponse({"code": 3, "message": "库存不足"})

        # 业务处理，保存数据
        if not request.user.is_authenticated():
            # 如果用户未登录，保存数据到cookie中
            cart_json = request.COOKIES.get("cart")
            if cart_json is not None:
                cart = json.loads(cart_json)
            else:
                cart = {}

            cart[sku_id] = count

            response = JsonResponse({"code": 0, "message": "修改成功"})
            response.set_cookie("cart", json.dumps(cart))
            return response
        else:
            # 如果用户已登录，保存数据到redis中
            redis_conn = get_redis_connection("default")
            user_id = request.user.id
            # cart = redis_conn.hgetall("cart_%s" % user_id)
            # # 将sku_id转换为bytes，对redis返回的字典cart进行操作
            # sku_id = sku_id.encode()
            # cart[sku_id] = count
            redis_conn.hset("cart_%s" % user_id, sku_id, count)
            # 返回结果， 返回Json数据
            return JsonResponse({"code": 0, "message": "修改成功"})


class DeleteCartView(View):
    """删除购物车数据"""
    def post(self, request):
        """"""
        # 获取参数
        sku_id = request.POST.get("sku_id")

        # 参数校验
        if not sku_id:
            return JsonResponse({"code": 1, "message": "参数缺失"})

        # 业务处理， 删除购物车数据
        if not request.user.is_authenticated():
            # 用户未登录，操作cookie
            cart_json = request.COOKIES.get("cart")
            if cart_json is not None:
                cart = json.loads(cart_json)
                # 判断cart字典中是否存在sku_id键
                if sku_id in cart:
                    # 删除cookie中cart字典的商品记录
                    del cart[sku_id]
                response = JsonResponse({"code": 0, "message": "删除成功"})
                response.set_cookie("cart", json.dumps(cart))
                return response
            else:
                return JsonResponse({"code": 0, "message": "删除成功"})
        else:
            # 用户已登录，操作redis
            redis_conn = get_redis_connection("default")
            user_id = request.user.id
            # 删除redis中的sku_id字段的记录
            redis_conn.hdel("cart_%s" % user_id, sku_id)
            return JsonResponse({"code": 0, "message": "删除成功"})












