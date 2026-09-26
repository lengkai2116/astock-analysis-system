"""2026 节假日表修正回归测试（trading_hours.py）

背景（一）：_DEFAULT_HOLIDAYS 曾混入错误日期（2026-09-15/16/17 实为 2025 中秋错位，
春节 01-28~02-03 为 2025 春节、端午 06-12~14 错位、国庆多 10-08）→ 依据《国务院办公厅
关于2026年部分节假日安排的通知》修正：
  元旦 1/1-1/3；春节 2/15-2/23；清明 4/4-4/6；劳动节 5/1-5/5；
  端午 6/19-6/21；中秋 9/25-9/27；国庆 10/1-10/7。

背景（二）483号（2026-09-26）：对「调休上班周末」用行情源交叉审计，原 6 条中已过的 5 条
（1/4、2/14、2/28、5/9、9/20）当日行情均为 0 行（实际休市），且 daily_cache 全历史
1268 个交易日内无任何周末有行情 → 用户拍板删除该 5 条（按周末规则回归非交易日）；
仅保留未来 2026-10-10 待验证（脚本 scripts/_483_trading_calendar_audit.py）。
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(k, None)

from app.utils.trading_hours import is_holiday


def _d(s: str) -> datetime:
    return datetime.strptime(s, '%Y-%m-%d')


class Test2026HolidayCalendar:
    """官方节假日日期（工作日部分）应为节假日"""

    def test_spring_festival_2026(self):
        # 春节 2/15-2/23（除夕 2/16、初一 2/17）；2/16-2/20、2/23 为工作日假期
        for s in ('2026-02-16', '2026-02-17', '2026-02-18', '2026-02-19',
                  '2026-02-20', '2026-02-23'):
            assert is_holiday(_d(s)) is True, f'{s} 应为春节假期'

    def test_qingming_labor_dragonboat_midautumn(self):
        # 清明 4/6（周一）、劳动节 5/1-5/5、端午 6/19（周五）、中秋 9/25（周五）
        for s in ('2026-04-06', '2026-05-01', '2026-05-04', '2026-05-05',
                  '2026-06-19', '2026-09-25'):
            assert is_holiday(_d(s)) is True, f'{s} 应为节假日'

    def test_national_day_2026(self):
        # 国庆 10/1-10/7（10/8 为正常工作日）
        for s in ('2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06',
                  '2026-10-07'):
            assert is_holiday(_d(s)) is True, f'{s} 应为国庆假期'


class Test2026WrongEntriesRemoved:
    """原错误条目已移除（本次修正核心）"""

    def test_mid_autumn_wrong_dates_not_holiday(self):
        # 2026-09-15/16/17 是正常交易日（原被误标为中秋假期 → 导致 09-16/17 采集缺口）
        for s in ('2026-09-15', '2026-09-16', '2026-09-17'):
            assert is_holiday(_d(s)) is False, f'{s} 不应是节假日（2026 中秋实为 9/25）'

    def test_spring_festival_2025_wrong_block_removed(self):
        # 2026-01-28~02-03 是 2025 春节；取其中的工作日（周中）断言非假期
        # （02-01 周日/02-02 周一？02-01 为周日属周末自然休市，不在此断言）
        for s in ('2026-01-28', '2026-01-29', '2026-01-30', '2026-02-02',
                  '2026-02-03'):
            assert is_holiday(_d(s)) is False, f'{s} 不应是 2026 春节假期'

    def test_dragonboat_wrong_dates_removed(self):
        # 2026-06-12~14 非端午（2026 端午为 6/19）；06-12 为周五（工作日），
        # 06-13/14 为周末属自然休市，不在此断言
        assert is_holiday(_d('2026-06-12')) is False, '2026-06-12 不应是端午假期'

    def test_national_day_extra_1008_removed(self):
        # 10/8（周四）为正常工作日
        assert is_holiday(_d('2026-10-08')) is False, '2026-10-08 应为正常工作日'

    def test_yuandan_0102_added(self):
        # 元旦 1/1-1/3（1/2 周五原缺失）
        assert is_holiday(_d('2026-01-02')) is True, '2026-01-02 应为元旦假期'


class TestWorkdayWeekends:
    """调休上班的周末 = 交易日（非节假日），股市照常开市"""

    def test_adjusted_workday_weekends_not_holiday(self):
        # 483号（2026-09-26）：原 6 条经行情源交叉审计删 5 条（当日均 0 行=实际休市），
        # 仅保留未来 2026-10-10（待其过后用 scripts/_483_trading_calendar_audit.py 复核）
        assert is_holiday(_d('2026-10-10')) is False, '2026-10-10 为调休上班日，不应是节假日'

    def test_removed_false_workdays_now_holiday(self):
        """483号删除的 5 个误标「调休上班」日 → 按周末规则回归非交易日"""
        for s in ('2026-01-04', '2026-02-14', '2026-02-28',
                  '2026-05-09', '2026-09-20'):
            assert is_holiday(_d(s)) is True, f'{s} 实际无行情（休市），应为非交易日'

    def test_normal_weekend_still_holiday(self):
        # 普通周末仍是节假日（非调休上班）
        assert is_holiday(_d('2026-08-02')) is True   # 周日
        assert is_holiday(_d('2026-07-25')) is True   # 周六

    def test_normal_weekday_not_holiday(self):
        assert is_holiday(_d('2026-07-27')) is False  # 周一
        assert is_holiday(_d('2026-11-11')) is False  # 周三
