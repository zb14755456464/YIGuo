from celery import Celery

import os
os.environ["DJANGO_SETTINGS_MODULE"] = "dailyfresh_13.settings"

# 放到celery服务器上时将注释打开
# import django
# django.setup()

# celery -A celery_tasks.tasks worker -l info

from django.core.mail import send_mail
from django.conf import settings
from django.template import loader
from goods.models import GoodsCategory, IndexGoodsBanner, IndexPromotionBanner
from goods.models import IndexCategoryGoodsBanner

# 创建celery应用对象
app = Celery("celery_tasks.tasks", broker="redis://10.211.55.5/2")


# 定义发送激活邮件任务
@app.task
def send_active_email(user_name, to_email, token):
    """发送激活邮件"""
    subject = "天天生鲜用户激活"  # 邮件标题
    body = ""  # 邮件体
    sender = settings.EMAIL_FROM  # 发件人
    receivers = [to_email]  # 接收人
    html_body = '<h1>尊敬的用户 %s, 感谢您注册天天生鲜！</h1>' \
                '<br/><p>请点击此链接激活您的帐号<a href="http://127.0.0.1:8000/users/active/%s">' \
                'http://127.0.0.1:8000/users/active/%s<a></p>' % (user_name, token, token) # html邮件体
    send_mail(subject, body, sender, receivers, html_message=html_body)


# 定义页面静态化的任务
@app.task
def generate_static_index_html():
    """生成主页的静态html文件"""
    # 需要查询的数据
    # 商品分类信息
    categorys = GoodsCategory.objects.all()

    # 首页轮播图信息, 按照index排序
    index_goods_banners = IndexGoodsBanner.objects.all().order_by("index")

    # 首页广告活动
    promotions_banners = IndexPromotionBanner.objects.all().order_by("index")

    # 分类商品展示  标题和图片
    for category in categorys:
        title_banners = IndexCategoryGoodsBanner.objects.filter(category=category, display_type=0).order_by("index")[:4]
        category.title_banners = title_banners
        image_banners = IndexCategoryGoodsBanner.objects.filter(category=category, display_type=1).order_by("index")[:4]
        category.image_banners = image_banners

    # 用户的购物车信息
    cart_num = 0

    # 处理模板页面
    context = {
        "categorys": categorys,
        "index_banners": index_goods_banners,
        "promotion_banners": promotions_banners,
        "cart_num": cart_num
    }

    # 加载模板
    template = loader.get_template("static_index.html")
    # 渲染模板,生成html数据
    html_data = template.render(context)
    # 保存产生的静态html数据
    file_path = os.path.join(settings.STATICFILES_DIRS[0], "index.html")
    with open(file_path, "w") as f:
        f.write(html_data)


















