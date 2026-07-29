"""
DataAwareMixin — 统一 DataManager 延迟注入

所有机会图谱引擎/服务类继承此 Mixin，避免重复实现 _get_dm() / _get_cache()。
测试时通过 _inject_dm(mock) 注入 Mock DataManager。
"""


class DataAwareMixin:
    """统一 DataManager 延迟注入 Mixin

    子类只需继承，调用 self._get_dm() 获取 DataManager 实例。
    测试时调用 self._inject_dm(mock_dm) 注入 Mock。
    """

    _dm = None

    def _get_dm(self):
        if self._dm is None:
            from app.data import DataManager
            self._dm = DataManager()
        return self._dm

    def _get_cache(self):
        return self._get_dm().cache

    def _inject_dm(self, dm):
        """测试用：注入 Mock DataManager"""
        self._dm = dm
