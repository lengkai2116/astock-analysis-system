"""
A股分析系统V3数据库迁移脚本
创建日期: 2026-06-03

新增表：
- signal_records (SignalRecord) — 轨A策略信号记录
- virtual_positions (VirtualPosition) — 轨B虚拟持仓
- trades (Trade) — 交易记录
- account_snapshots (AccountSnapshot) — 账户快照
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db

def upgrade():
    """执行数据库迁移 — 创建验证/账户/交易表"""
    app = create_app()
    with app.app_context():
        print("开始V3数据库迁移...")
        
        # 导入需要建表的模型
        from app.models.verification import SignalRecord, VirtualPosition
        from app.models.trade import Trade, AccountSnapshot
        
        # 创建所有尚未存在的表
        db.create_all()
        print("✅ 新表创建成功")
        print(f"  - signal_records (SignalRecord)")
        print(f"  - virtual_positions (VirtualPosition)")
        print(f"  - trades (Trade)")
        print(f"  - account_snapshots (AccountSnapshot)")
        
        print("V3迁移完成！")

def downgrade():
    """回滚 — 删除V3新增的表"""
    app = create_app()
    with app.app_context():
        print("开始回滚V3数据库迁移...")
        
        from app.models.verification import SignalRecord, VirtualPosition
        from app.models.trade import Trade, AccountSnapshot
        
        # 删除表
        SignalRecord.__table__.drop(db.engine, checkfirst=True)
        VirtualPosition.__table__.drop(db.engine, checkfirst=True)
        Trade.__table__.drop(db.engine, checkfirst=True)
        AccountSnapshot.__table__.drop(db.engine, checkfirst=True)
        
        print("✅ V3新增表删除成功")
        print("回滚完成！")

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        downgrade()
    else:
        upgrade()
