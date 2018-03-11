from django.shortcuts import render, redirect
from django.views.generic import View
from utils.views import LoginRequiredMixin, LoginRequiredJsonMixin, TransactionAtomicMixin
from django.core.urlresolvers import reverse
from goods.models import GoodsSKU
from django_redis import get_redis_connection
from users.models import Address
from django.http import JsonResponse, HttpResponse
from orders.models import OrderInfo, OrderGoods
from django_redis import get_redis_connection
from django.utils import timezone
from django.db import transaction
from django.core.paginator import Paginator
from django.core.cache import cache
from alipay import AliPay
import os
from django.conf import settings
import time

# Create your views here.


class PlaceOrderView(LoginRequiredMixin, View):
    """确认订单页面"""
    def post(self, request):
        """接受订单数据，并提供订单确认页面"""
        # 接受参数
        sku_ids = request.POST.getlist("sku_ids")  # 要下单的商品id sku_ids = [1,2,3,4,5]
        count = request.POST.get("count")  # 在商品详情页面点击立即购买，进入到确认订单页面，才会有这个数量的参数
                                           # 这个count参数不是列表，只是详情页商品的数量，这个字段不一定有

        # 校验
        if not sku_ids:
            # 跳转到购物车页面
            return redirect(reverse("cart:info"))

        redis_conn = get_redis_connection("default")

        user_id = request.user.id
        # 查询地址信息、商品信息
        # 地址信息
        try:
            # address = address = Address.objects.filter(user_id=user_id).latest("create_time")
            address = address = Address.objects.filter(user=request.user).latest("create_time")
        except Address.DoesNotExist:
            address = None

        skus = []  # 用于传递给页面
        total_skus_amount = 0  # 商品总金额
        total_count = 0  # 商品总数量
        total_amount = 0  # 包含运费的总金额
        # 商品信息
        if count is None:
            # 如果是从购物车页面跳转而来，要从购物车中获取商品数量的信息
            cart = redis_conn.hgetall("cart_%s" % user_id)
            for sku_id in sku_ids:
                try:
                    sku = GoodsSKU.objects.get(id=sku_id)
                except GoodsSKU.DoesNotExist:
                    # 跳转到购物车页面
                    return redirect(reverse("cart:info"))
                # 从购物车中获取商品数量
                sku_count = cart.get(sku_id.encode())
                sku_count = int(sku_count)

                # 计算商品的金额
                amount = sku.price * sku_count
                sku.amount = amount
                sku.count = sku_count
                skus.append(sku)

                # 累计总金额和数量
                total_skus_amount += amount
                total_count += sku_count
        else:
            # 如果是从商品详情页面的立即购买跳转而来，则不用读取购物车的商品数量，直接使用count字段
            for sku_id in sku_ids:   # 虽然只有一个商品 但是也是使用列表获取而来 [id]
                try:
                    sku = GoodsSKU.objects.get(id=sku_id)
                except GoodsSKU.DoesNotExist:
                    # 跳转到购物车页面
                    return redirect(reverse("cart:info"))

                try:
                    count = int(count)
                except Exception:
                    return redirect(reverse("goods:detail", args=(sku_id,)))

                # 判断库存
                if count > sku.stock:
                    return redirect(reverse("goods:detail", args=(sku_id,)))

                # 计算商品的金额
                amount = sku.price * count
                sku.amount = amount
                sku.count = count
                skus.append(sku)

                total_skus_amount += amount
                total_count += count

                # 将这个商品放到购物车中，方便用户下单时出现问题，还能从购物车中找到信息
                redis_conn.hset("cart_%s" % user_id, sku_id, count)

        trans_cost = 10  # 运费
        total_amount = total_skus_amount + trans_cost

        # 返回前端页面
        context = {
            "skus": skus,
            "address": address,
            "total_count": total_count,
            "total_skus_amount": total_skus_amount,
            "total_amount": total_amount,
            "trans_cost": trans_cost,
            "sku_ids": ",".join(sku_ids)
        }

        return render(request, "place_order.html", context)


class CommitOrderView(LoginRequiredJsonMixin, TransactionAtomicMixin, View):
    """提交订单"""
    def post(self, request):
        """接受订单数据， 保存订单"""
        # 获取要保存的订单的数据
        # user 地址id、支付方式、商品id与  数量(从购物车中获取)
        user = request.user
        address_id = request.POST.get("address_id")
        pay_method = request.POST.get("pay_method")  # 支付方式  "1"
        sku_ids = request.POST.get("sku_ids")  # "1,2,3,4,5"

        # 进行校验
        # 判断地址是否存在
        try:
            address = Address.objects.get(id=address_id, user=user)
        except Address.DoesNotExist:
            return JsonResponse({"code": 2, "message": "地址不存在"})

        # 判断支付方式
        pay_method = int(pay_method)
        if pay_method not in OrderInfo.PAY_METHODS.keys():
            return JsonResponse({"code": 3, "message": "不支持的支付方式"})

        # 判断商品存在与否
        sku_ids = sku_ids.split(",")

        # 获取购物车数据
        redis_conn = get_redis_connection("default")
        cart = redis_conn.hgetall("cart_%s" % user.id)

        # 创建一个订单的基本信息数据 OrderInfo  订单商品表的数据会用到这个

        # 自定义的订单编号格式 "20171026111111用户id"
        order_id = timezone.now().strftime("%Y%m%d%H%M%S") + str(user.id)

        # 创建事务用到的保存点
        save_id = transaction.savepoint()

        try:
            order = OrderInfo.objects.create(
                order_id=order_id,
                user=user,
                address=address,
                total_amount=0,
                trans_cost=10,  # 运费暂时写死
                pay_method=pay_method
            )

            # 遍历商品sku_ids，判断商品信息合理与否的同时保存到订单的商品表
            total_count = 0
            total_amount = 0
            for sku_id in sku_ids:
                # 对一商品尝试下单三次
                for i in range(3):
                    try:
                        sku = GoodsSKU.objects.get(id=sku_id)
                    except GoodsSKU.DoesNotExist:
                        # 回退到保存点
                        transaction.savepoint_rollback(save_id)
                        return JsonResponse({"code": 4, "message": "商品信息有误"})

                    # 从购物车中获取用户订购的商品的数量
                    count = cart.get(sku_id.encode())
                    count = int(count)

                    # 判断商品的库存够不够
                    if count > sku.stock:
                        transaction.savepoint_rollback(save_id)
                        return JsonResponse({"code": 5, "message": "库存不足"})

                    new_stock = sku.stock - count
                    new_sales = sku.sales + count

                    # 采用乐观锁的方式，更新商品的库存，销量
                    # update会返回更新成功的数据数目

                    result = GoodsSKU.objects.filter(id=sku_id, stock=sku.stock).update(stock=new_stock, sales=new_sales)
                    # update goods_sku set stock=new_stock, sales=new_sales where id=sku_id and stock=sku.stock
                    if result == 0 and i < 2:
                        # 表示库存更新失败，下单失败
                        continue
                    elif result == 0 and i == 2:
                        # 表示尝试了三次都失败
                        transaction.savepoint_rollback(save_id)
                        return JsonResponse({"code": 6, "message": "下单失败"})

                    # 在订单商品表中保存商品的信息
                    OrderGoods.objects.create(
                        order=order,
                        sku=sku,
                        count=count,
                        price=sku.price,
                    )

                    # 计算订单的总金额
                    total_amount += (sku.price * count)
                    # 计算订单商品的总数量
                    total_count += count

                    # 对这个商品下单成功
                    break

            # 更新订单信息表数据，处理总金额总数量
            order.total_amount = total_amount + 10
            order.total_count = total_count
            order.save()
        except Exception as e:
            print(e)
            # 出现了任何异常信息，都要回滚事务
            transaction.savepoint_rollback(save_id)
            return JsonResponse({"code": 7, "message": "下单失败"})

        # 提交数据的事务操作
        transaction.savepoint_commit(save_id)

        # 将处理后的购物车数据cart保存到redis中
        # sku_ids =[1,2,3,4,5]
        #
        # redis_conn.hdel("cart_%s" % user.id, 1,2,3,4,5)

        redis_conn.hdel("cart_%s" % user.id, *sku_ids)

        # 返回给前端处理的结果， 返回json数据
        return JsonResponse({"code": 0, "message": "下单成功"})


class UserOrdersView(LoginRequiredMixin, View):
    """用户订单"""
    def get(self, request, page):
        user = request.user
        # 查询订单,按最新的时间进行查询
        orders = user.orderinfo_set.all().order_by("-create_time")
        # 往每个订单中添加前端需要的信息
        for order in orders:
            order.status_name = OrderInfo.ORDER_STATUS[order.status]
            order.pay_method_name = OrderInfo.PAY_METHODS[order.pay_method]
            order.skus = []
            order_skus = order.ordergoods_set.all()
            for order_sku in order_skus:
                sku = order_sku.sku
                sku.count = order_sku.count
                sku.amount = sku.price * sku.count
                order.skus.append(sku)

        # 分页
        paginator = Paginator(orders, 3)
        # 获取页码的列表
        pages = paginator.page_range
        # 获取总页数
        num_pages = paginator.num_pages
        # 当前页转化为数字
        page = int(page)

        # 1.如果总页数<=5
        # 2.如果当前页是前3页
        # 3.如果当前页是后3页,
        # 4.既不是前3页，也不是后3页
        if num_pages <= 5:
            pages = range(1, num_pages + 1)
        elif page <= 3:
            pages = range(1, 6)
        elif (num_pages - page) <= 2:
            pages = range(num_pages - 4, num_pages + 1)
        else:
            pages = range(page - 2, page + 3)

        # 取第page页的内容 has_previous has_next number
        page_orders = paginator.page(page)

        context = {
            "orders": page_orders,
            "page": page,
            "pages": pages
        }

        return render(request, "user_center_order.html", context)


class CommentView(LoginRequiredMixin, View):
    """订单评论"""
    def get(self, request, order_id):
        """提供评论页面"""
        user = request.user
        try:
            order = OrderInfo.objects.get(order_id=order_id, user=user)
        except OrderInfo.DoesNotExist:
            return redirect(reverse("orders:info"))

        order.status_name = OrderInfo.ORDER_STATUS[order.status]
        order.skus = []
        order_skus = order.ordergoods_set.all()
        for order_sku in order_skus:
            sku = order_sku.sku
            sku.count = order_sku.count
            sku.amount = sku.price * sku.count
            order.skus.append(sku)

        return render(request, "order_comment.html", {"order": order})

    def post(self, request, order_id):
        """处理评论内容"""
        user = request.user
        try:
            order = OrderInfo.objects.get(order_id=order_id, user=user)
        except OrderInfo.DoesNotExist:
            return redirect(reverse("orders:info"))

        # 获取评论条数
        total_count = request.POST.get("total_count")
        total_count = int(total_count)

        for i in range(1, total_count + 1):
            sku_id = request.POST.get("sku_%d" % i)
            content = request.POST.get('content_%d' % i, '')
            try:
                order_goods = OrderGoods.objects.get(order=order, sku_id=sku_id)
            except OrderGoods.DoesNotExist:
                continue

            order_goods.comment = content
            order_goods.save()

            # 清除商品详情缓存
            cache.delete("detail_%s" % sku_id)

        order.status = OrderInfo.ORDER_STATUS_ENUM["FINISHED"]
        order.save()

        return redirect(reverse("orders:info", kwargs={"page": 1}))


class PayView(LoginRequiredJsonMixin, View):
    """支付宝支付视图"""
    def post(self, request):
        # 订单编号  order_id
        order_id = request.POST.get("order_id")

        if not order_id:
            return JsonResponse({"code": 2, "message": "缺失订单编号"})

        # 获取订单信息
        try:
            order = OrderInfo.objects.get(order_id=order_id, user=request.user,
                                          status=OrderInfo.ORDER_STATUS_ENUM["UNPAID"],
                                          pay_method=OrderInfo.PAY_METHODS_ENUM["ALIPAY"])
        except OrderInfo.DoesNotExist:
            return JsonResponse({"code": 3, "message": "订单信息错误"})

        # 构建alipay支付工具对象
        alipay = AliPay(
            appid=settings.ALIPAY_APPID,  # 沙箱模式中的appid
            app_notify_url=None,  # 默认回调url
            app_private_key_path=os.path.join(settings.BASE_DIR, "apps/orders/app_private_key.pem"),
            alipay_public_key_path=os.path.join(settings.BASE_DIR, "apps/orders/alipay_public_key.pem"),  # 支付宝的公钥，验证支付宝回传消息使用，不是你自己的公钥,
            sign_type="RSA2",  # RSA 或者 RSA2
            debug=True  # 默认False, 沙箱模式配置为true
        )

        # 借助alipay对象，向支付宝发起支付请求
        # 电脑网站支付，需要跳转到https://openapi.alipaydev.com/gateway.do? + order_string
        order_string = alipay.api_alipay_trade_page_pay(
            out_trade_no=order_id,  # 订单编号
            total_amount=str(order.total_amount),   # 订单金额
            subject="天天生鲜%s" % order_id,   # 订单描述信息
            return_url=None, # 订单成功返回的信息
            notify_url=None  # 可选, 不填则使用默认notify url
        )

        # 返回json数据
        alipay_url = settings.ALIPAY_URL + "?" + order_string
        return JsonResponse({"code": 0, "message": "发起支付成功", "url": alipay_url})


class CheckPayStatusView(LoginRequiredJsonMixin, View):
    """检查支付结果"""
    def get(self, request):
        order_id = request.GET.get("order_id")

        if not order_id:
            return JsonResponse({"code": 2, "message": "缺少订单号"})

        # 获取订单信息
        try:
            order = OrderInfo.objects.get(order_id=order_id, user=request.user,
                                          status=OrderInfo.ORDER_STATUS_ENUM["UNPAID"],
                                          pay_method=OrderInfo.PAY_METHODS_ENUM["ALIPAY"])
        except OrderInfo.DoesNotExist:
            return JsonResponse({"code": 3, "message": "订单信息错误"})

        # 构建alipay支付工具对象
        alipay = AliPay(
            appid=settings.ALIPAY_APPID,  # 沙箱模式中的appid
            app_notify_url=None,  # 默认回调url
            app_private_key_path=os.path.join(settings.BASE_DIR, "apps/orders/app_private_key.pem"),
            alipay_public_key_path=os.path.join(settings.BASE_DIR, "apps/orders/alipay_public_key.pem"),  # 支付宝的公钥，验证支付宝回传消息使用，不是你自己的公钥,
            sign_type="RSA2",  # RSA 或者 RSA2
            debug=True  # 默认False, 沙箱模式配置为true
        )

        # 借助alipay工具查询支付结果
        while True:
            response = alipay.api_alipay_trade_query(order_id)
            code = response.get("code")
            trade_status = response.get("trade_status")
            if code == "10000" and trade_status == "TRADE_SUCCESS":
                # 表示用户支付成功
                order.trade_id = response.get("trade_no") # 支付宝的交易标号
                order.status = OrderInfo.ORDER_STATUS_ENUM["UNCOMMENT"]  # 设置订单状态为待评价
                order.save()
                return JsonResponse({"code": 0, "message": "支付成功"})
            elif code == "40004" or (code == "10000" and trade_status == "WAIT_BUYER_PAY"):
                # 表示支付宝订单还没创建好， 或者用户还未支付
                time.sleep(10)
                continue
            else:
                return JsonResponse({"code": 4, "message": "支付失败"})











