"""461-3：size_factor 流通市值单位修正测试（461-13 后更新）

460 §五 P4：size_factor 用 circ_mv 分档（large_cap>500亿/mid>100亿/small），
但未 ×1e4 换算，阈值差 10 倍（原 circ>5e10 万元 视作 5e12 元=5万亿元判大盘，
与 445-A2 确立的 daily_basic 万元口径、_compute_style_exposure 的 total_mv*1e4 判据矛盾）。

461-3 修复：circ_mv 万元 ×1e4 = 元，对齐 _compute_style_exposure（total_mv*1e4>5e10=500亿元）。
事实层单位换算修正，不碰判定逻辑。

461-13 更新：size_factor 实证为算而不出死键（app 层 tags 零消费者，《460 §五 P8》），已从 data_daemon
预计算组移除。461-3 修的口径 bug 随字段删除一并消失（无消费者即无 bug 影响面）。
本测试改为断言 size_factor 死键已自 data_daemon 移除（死键清理回归）。
"""
import inspect
import data_daemon

_MOD = inspect.getsource(data_daemon)


class TestSizeFactorRemoval:
    def test_size_factor_prod_removed(self):
        """_raw2_one 风格组不再产出 size_factor（461-13 死键清理）"""
        assert "_sz = 'unknown'" not in _MOD
        assert "'size_factor': _sz" not in _MOD
        assert "circ * 1e4 > 5e10" not in _MOD

    def test_style_exposure_kept(self):
        """风格组保留 style_exposure（317号/雷达服务消费）"""
        assert "'style_exposure'" in _MOD
