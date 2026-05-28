"""
A股分析系统V2数据库迁移脚本
创建日期: 2026-05-24
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.strategy import StrategyOutput, StrategyTemplateV2, StrategySignal, StrategyTemplateType

def upgrade():
    """执行数据库迁移"""
    app = create_app()
    with app.app_context():
        print("开始数据库迁移...")
        
        db.create_all()
        print("✅ 数据表创建成功")
        
        print("迁移完成！")

def downgrade():
    """回滚数据库迁移"""
    app = create_app()
    with app.app_context():
        print("开始回滚数据库迁移...")
        
        db.drop_all()
        print("✅ 数据表删除成功")
        
        print("回滚完成！")

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        downgrade()
    else:
        upgrade()
