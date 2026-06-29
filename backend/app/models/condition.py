"""
条件库管理模型

条件注册表：存储全量条件（~100-120条），含可实现性标注、使用统计
此表与 test.db（SQLite）中的其他业务表同库，不影响现有查询逻辑。

SQLite影响评估：
  - 系统现有 DATABASE_URL=sqlite:///test.db（Flask-SQLAlchemy 管理）
  - Condition表约100-120条记录，占用空间极小（<1MB）
  - 索引：condition_id(唯一)、category、data_readiness
  - 不影响现有 daily_data(610万行)/signals/holdings 等表的查询
  - Flask-Migrate 自动管理迁移
"""
from app import db
from datetime import datetime
from sqlalchemy import JSON, UniqueConstraint


class ConditionRegistry(db.Model):
    """条件注册表 — 条件库统一管理"""
    __tablename__ = 'condition_registry'

    id = db.Column(db.Integer, primary_key=True)
    condition_id = db.Column(db.String(80), nullable=False, unique=True, index=True)  # 唯一标识
    name = db.Column(db.String(100), nullable=False)                                   # 标准名称
    display_name = db.Column(db.String(200))                                           # 用户端显示名
    category = db.Column(db.String(50), index=True)                                    # 分类
    category_path = db.Column(JSON, default=list)                                      # 归类路径
    difficulty_level = db.Column(db.String(20), default='入门')                         # 入门|进阶|高级|专业
    data_source = db.Column(db.String(50))                                              # 数据源标识
    data_readiness = db.Column(db.String(20), default='pending', index=True)            # ready|qmt_needed|insufficient
    default_params = db.Column(JSON, default=dict)                                      # 默认参数及范围
    linked_strategies = db.Column(JSON, default=list)                                   # 关联策略
    related_conditions = db.Column(JSON, default=list)                                  # 关联条件ID列表
    description = db.Column(JSON, default=dict)                                         # 说明体系（7字段）

    # 使用统计
    usage_count = db.Column(db.Integer, default=0)                                      # 被多少条规则引用
    last_used = db.Column(db.DateTime, nullable=True)                                   # 最近一次被引用时间

    # 管理信息
    notes = db.Column(db.Text, default='')                                              # 内部备注
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'condition_id': self.condition_id,
            'name': self.name,
            'display_name': self.display_name,
            'category': self.category,
            'category_path': self.category_path,
            'difficulty_level': self.difficulty_level,
            'data_source': self.data_source,
            'data_readiness': self.data_readiness,
            'default_params': self.default_params,
            'linked_strategies': self.linked_strategies,
            'related_conditions': self.related_conditions,
            'description': self.description,
            'usage_count': self.usage_count,
            'last_used': self.last_used.isoformat() if self.last_used else None,
            'notes': self.notes,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }

    def to_overview(self):
        """概览视图（dashboard用，不含详细字段）"""
        return {
            'condition_id': self.condition_id,
            'name': self.name,
            'display_name': self.display_name,
            'category': self.category,
            'difficulty_level': self.difficulty_level,
            'data_readiness': self.data_readiness,
            'usage_count': self.usage_count,
        }
