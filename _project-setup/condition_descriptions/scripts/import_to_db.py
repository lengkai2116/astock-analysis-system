#!/usr/bin/env python3
"""
将 output/condition_descriptions.json 导入后端 condition_registry 表

使用方法：
  python3 import_to_db.py

前置条件：
  - 后端服务已启动，DATABASE_URL 配置正确
  - condition_registry 表已创建（通过 Flask-Migrate）
"""
import json
import os
import sys
from pathlib import Path

# 确保后端包路径可引用
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app import create_app, db
from app.models.condition import ConditionRegistry

SCRIPT_DIR = Path(__file__).parent
INPUT_FILE = SCRIPT_DIR.parent / "output" / "condition_descriptions.json"
INPUT_LIST = SCRIPT_DIR.parent / "conditions_input.json"


def main():
    if not INPUT_FILE.exists():
        print(f"❌ 未找到说明文件: {INPUT_FILE}")
        print(f"   请先运行 run_generation.sh 生成说明")
        return

    app = create_app()
    with app.app_context():
        # 确保表存在（自建表，避免依赖手动 migrate）
        db.create_all()
        print(f"📦 数据库已就绪: {db.engine.url}")
        # 加载生成的说明
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            descriptions = json.load(f)

        # 加载条件清单（获取基础信息）
        with open(INPUT_LIST, "r", encoding="utf-8") as f:
            conditions = json.load(f)

        # 构建条件ID→基础信息映射
        condition_map = {c["condition_id"]: c for c in conditions}

        imported = 0
        skipped = 0

        for condition_id, desc in descriptions.items():
            existing = ConditionRegistry.query.filter_by(condition_id=condition_id).first()

            if existing:
                # 更新描述
                existing.description = desc
                skipped += 1
            else:
                # 新建记录
                info = condition_map.get(condition_id, {})
                condition = ConditionRegistry(
                    condition_id=condition_id,
                    name=info.get("name", condition_id),
                    display_name=info.get("display_name"),
                    category=info.get("category"),
                    category_path=info.get("category_path", []),
                    difficulty_level=info.get("difficulty_level", "入门"),
                    data_source=info.get("data_source"),
                    data_readiness=info.get("data_readiness", "ready"),
                    default_params=info.get("default_params", {}),
                    linked_strategies=info.get("linked_strategies", []),
                    related_conditions=info.get("related_conditions", []),
                    description=desc,
                    notes=info.get("notes", ""),
                )
                db.session.add(condition)
                imported += 1

        db.session.commit()
        print(f"✅ 导入完成")
        print(f"   - 新建: {imported}")
        print(f"   - 更新: {skipped}")
        print(f"   - 合计: {imported + skipped}")


if __name__ == "__main__":
    main()
