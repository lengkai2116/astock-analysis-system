"""
筹码分析模块数据库迁移脚本 V1
用于创建PostgreSQL中的筹码相关表
"""
import sys
import os
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import Column, Integer, String, Date, Numeric, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class ChipDistribution(Base):
    """筹码分布表 - 存储每日筹码分布数据（简化版）"""
    __tablename__ = 'chip_distribution'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(10), nullable=False, comment='股票代码')
    trade_date = Column(Date, nullable=False, comment='交易日期')
    
    # 筹码指标
    ssrp = Column(Numeric(10, 2), comment='市场平均成本')
    asr = Column(Numeric(6, 4), comment='活跃浮筹比例')
    concentration = Column(Numeric(6, 4), comment='筹码集中度')
    profit_ratio = Column(Numeric(6, 4), comment='筹码获利率')
    cyqkl = Column(Numeric(6, 4), comment='K线穿越筹码强度')
    
    # 筹码峰位置（JSON格式存储前3个主要筹码峰）
    peak_positions = Column(Text, comment='筹码峰位置 JSON')
    
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    __table_args__ = (
        Index('idx_chip_ts_code_date', 'ts_code', 'trade_date', unique=True),
        {'comment': '筹码分布表'}
    )

class ChipIndicator(Base):
    """筹码指标表 - 存储每日详细筹码指标"""
    __tablename__ = 'chip_indicators'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(10), nullable=False, comment='股票代码')
    trade_date = Column(Date, nullable=False, comment='交易日期')
    
    # 基础筹码指标
    ssrp = Column(Numeric(10, 2), comment='市场平均成本')
    asr_10 = Column(Numeric(6, 4), comment='±10%浮筹比例')
    asr_20 = Column(Numeric(6, 4), comment='±20%浮筹比例')
    concentration = Column(Numeric(6, 4), comment='筹码集中度')
    profit_ratio = Column(Numeric(6, 4), comment='筹码获利率')
    
    # 筹码转移相关
    transfer_rate_5 = Column(Numeric(6, 4), comment='5日筹码转移率')
    transfer_rate_20 = Column(Numeric(6, 4), comment='20日筹码转移率')
    
    # CYQK指标
    cyqkl = Column(Numeric(6, 4), comment='K线穿越强度')
    
    # 支撑阻力位
    support_levels = Column(Text, comment='支撑位 JSON')
    resistance_levels = Column(Text, comment='阻力位 JSON')
    
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    __table_args__ = (
        Index('idx_chip_ind_ts_code_date', 'ts_code', 'trade_date', unique=True),
        {'comment': '筹码指标表'}
    )

class ChipStageRecord(Base):
    """筹码阶段识别表 - 识别主力建仓/洗盘/拉升/出货阶段"""
    __tablename__ = 'chip_stage_records'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(10), nullable=False, comment='股票代码')
    trade_date = Column(Date, nullable=False, comment='交易日期')
    
    # 阶段识别
    stage = Column(String(20), nullable=False, comment='阶段: accumulation/washing/rising/distribution/support')
    stage_score = Column(Numeric(5, 2), comment='阶段得分')
    
    # 阶段特征
    score_accumulation = Column(Numeric(5, 2), comment='建仓期得分')
    score_washing = Column(Numeric(5, 2), comment='洗盘期得分')
    score_rising = Column(Numeric(5, 2), comment='拉升期得分')
    score_distribution = Column(Numeric(5, 2), comment='出货期得分')
    score_support = Column(Numeric(5, 2), comment='支撑位得分')
    
    # 风险提示
    risk_level = Column(String(20), comment='风险等级: low/medium/high/extreme')
    risk_note = Column(Text, comment='风险说明')
    
    # 信号输出
    signal_type = Column(String(20), comment='信号: watch/buy/hold/reduce/sell/risk')
    signal_confidence = Column(Numeric(5, 2), comment='信号置信度')
    
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    __table_args__ = (
        Index('idx_chip_stage_ts_code_date', 'ts_code', 'trade_date', unique=True),
        Index('idx_chip_stage', 'stage'),
        {'comment': '筹码阶段识别表'}
    )

def upgrade():
    """执行升级"""
    app = create_app()
    with app.app_context():
        engine = db.engine
        
        # 创建表
        print("📊 创建筹码相关表...")
        Base.metadata.create_all(engine)
        print("✅ 表创建成功！")
        
        # 显示已创建的表
        inspector = db.inspect(engine)
        tables = inspector.get_table_names()
        print(f"📋 当前数据库表: {tables}")
        
        chip_tables = [t for t in tables if 'chip' in t.lower()]
        print(f"🎯 筹码相关表: {chip_tables}")

def downgrade():
    """执行降级（谨慎使用！）"""
    app = create_app()
    with app.app_context():
        engine = db.engine
        
        print("⚠️ 删除筹码相关表...")
        ChipStageRecord.__table__.drop(engine, checkfirst=True)
        ChipIndicator.__table__.drop(engine, checkfirst=True)
        ChipDistribution.__table__.drop(engine, checkfirst=True)
        print("✅ 删除完成！")

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='筹码分析模块数据库迁移')
    parser.add_argument('--downgrade', action='store_true', help='执行降级（删除表）')
    
    args = parser.parse_args()
    
    if args.downgrade:
        confirm = input("⚠️ 警告：此操作将删除所有筹码相关表！确认吗？(yes/no): ")
        if confirm.lower() == 'yes':
            downgrade()
        else:
            print("❌ 操作取消")
    else:
        upgrade()
