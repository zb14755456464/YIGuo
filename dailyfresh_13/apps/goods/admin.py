from django.contrib import admin

# Register your models here.
from goods.models import GoodsCategory, Goods, GoodsSKU, GoodsImage
from goods.models import IndexGoodsBanner, IndexCategoryGoodsBanner, IndexPromotionBanner
from celery_tasks.tasks import generate_static_index_html
from django.core.cache import cache


class BaseAdmin(admin.ModelAdmin):
    """admin站点的模型管理类，可以控制admin站点对于模型的展示修改等操作"""
    def save_model(self, request, obj, form, change):
        """admin站点在模型保存数据的时候调用"""
        # obj是要保存的模型对象（models里的类的对象）
        # 将数据保存到数据库中
        obj.save()

        # 调用生成静态页面的celery异步任务
        generate_static_index_html.delay()

        # 清除主页的缓存数据
        cache.delete("index_page_data")

    def delete_model(self, request, obj):
        """admin站点在模型删除数据的时候调用"""
        # 从数据库中删除
        obj.delete()

        # 调用生成静态页面的celery异步任务
        generate_static_index_html.delay()

        # 清除主页的缓存数据
        cache.delete("index_page_data")


class GoodsCategoryAdmin(BaseAdmin):
    """商品分类信息的管理类"""
    # 在这里填充控制amdin站点的展示效果
    pass


class IndexPromotionBannerAdmin(BaseAdmin):
    """"""
    pass

admin.site.register(GoodsCategory, GoodsCategoryAdmin)
admin.site.register(Goods)
admin.site.register(GoodsSKU)
admin.site.register(GoodsImage)
admin.site.register(IndexGoodsBanner)
admin.site.register(IndexCategoryGoodsBanner)
admin.site.register(IndexPromotionBanner, IndexPromotionBannerAdmin)
