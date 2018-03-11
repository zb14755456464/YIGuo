from haystack import indexes
from goods.models import GoodsSKU


class GoodsSKUIndex(indexes.SearchIndex, indexes.Indexable):
    """索引类， 告诉haystack在建立数据索引的时候使用"""
    text = indexes.CharField(document=True, use_template=True)

    def get_model(self):
        """"""
        return GoodsSKU

    def index_queryset(self, using=None):
        """"""
        return self.get_model().objects.all()
