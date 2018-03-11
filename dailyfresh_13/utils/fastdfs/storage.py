from django.core.files.storage import Storage
from fdfs_client.client import Fdfs_client
from django.conf import settings


class FastDFSStorage(Storage):
    """对接fastdfs的文件存储工具类，被django使用"""
    def __init__(self, client_conf=None, fastdfs_url=None):
        if client_conf is None:
            client_conf = settings.FASTDFS_CLIENT_CONF

        self.client_conf = client_conf

        if fastdfs_url is None:
            fastdfs_url = settings.FASTDFS_URL

        self.fastdfs_url = fastdfs_url

    def _save(self, name, content):
        """保存 context是用户上传过来的文件对象"""
        # 从文件对象中读取文件数据
        file_data = content.read()
        # 创建用户存储fastdfs的客户端
        client = Fdfs_client(self.client_conf)
        # 上传文件内容到fastdfs中
        try:
            ret = client.upload_by_buffer(file_data)
            # ret的返回值格式 {'Group name':'group1','Status':'Upload successed.', 'Remote file_id':'group1/M00/00/00/
            # wKjzh0_xaR63RExnAAAaDqbNk5E1398.py','Uploaded size':'6.0KB','Local file name':'test'
            # , 'Storage IP':'192.168.243.133'}
        except Exception as e:
            print(e)
            raise

        if ret.get("Status") == "Upload successed.":
            # 表示上传成功
            file_id = ret.get("Remote file_id")
            # 返回file_id， 也就是文件名，django会保存到数据库中
            return file_id
        else:
            raise Exception("上传到FastDFS失败")

    def _open(self, name, mode='rb'):
        """打开"""
        pass

    def exists(self, name):
        """判断文件name是否存在"""
        return False

    def url(self, name):
        """返回完整的文件访问url路径"""
        # name是文件的名字，也就是file_id
        # file_id = "group1/M00/00/00/wKjzh0_xaR63RExnAAAaDqbNk5E1398.py"
        # return "http://10.211.55.5:8888/" + name
        return self.fastdfs_url + name