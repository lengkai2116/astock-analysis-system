"""
数据迁移工具（355号方案规则4.6）
===================================
提供数据库迁移和数据转换功能。

支持功能：
1. 表结构迁移
2. 数据格式转换
3. 分库迁移
4. 数据备份和恢复
"""

import os
import sqlite3
import logging
from typing import Dict, List, Optional
from datetime import datetime
import shutil

logger = logging.getLogger(__name__)


class Migration:
    """数据迁移管理器"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
        os.makedirs(self._backup_dir, exist_ok=True)
        
    def backup_database(self, backup_name: str = None) -> str:
        """备份数据库
        
        Args:
            backup_name: 备份名称（可选）
            
        Returns:
            备份文件路径
        """
        if backup_name is None:
            backup_name = datetime.now().strftime('%Y%m%d_%H%M%S')
            
        backup_path = os.path.join(self._backup_dir, f'{backup_name}.db')
        
        try:
            shutil.copy2(self.db_path, backup_path)
            logger.info(f"数据库备份成功: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"数据库备份失败: {e}")
            raise
            
    def restore_database(self, backup_path: str) -> bool:
        """恢复数据库
        
        Args:
            backup_path: 备份文件路径
            
        Returns:
            是否恢复成功
        """
        try:
            shutil.copy2(backup_path, self.db_path)
            logger.info(f"数据库恢复成功: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"数据库恢复失败: {e}")
            return False
            
    def migrate_table_structure(self, table_name: str, new_columns: List[Dict]):
        """迁移表结构
        
        Args:
            table_name: 表名
            new_columns: 新列定义 [{'name': 'col_name', 'type': 'col_type'}, ...]
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 获取现有列
            cursor.execute(f"PRAGMA table_info({table_name})")
            existing_columns = {row[1] for row in cursor.fetchall()}
            
            # 添加新列
            for col in new_columns:
                if col['name'] not in existing_columns:
                    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col['name']} {col['type']}")
                    logger.info(f"添加列: {table_name}.{col['name']} {col['type']}")
                    
            conn.commit()
            logger.info(f"表结构迁移完成: {table_name}")
            
        except Exception as e:
            logger.error(f"表结构迁移失败: {table_name}, {e}")
            conn.rollback()
        finally:
            conn.close()
            
    def convert_date_format(self, table_name: str, date_column: str, 
                           from_format: str, to_format: str):
        """转换日期格式
        
        Args:
            table_name: 表名
            date_column: 日期列名
            from_format: 原格式（如 '%Y%m%d'）
            to_format: 目标格式（如 '%Y-%m-%d'）
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 查询需要转换的数据
            cursor.execute(f"SELECT rowid, {date_column} FROM {table_name}")
            rows = cursor.fetchall()
            
            converted_count = 0
            for rowid, date_value in rows:
                if date_value:
                    try:
                        # 转换日期格式
                        from datetime import datetime
                        date_obj = datetime.strptime(str(date_value), from_format)
                        new_date = date_obj.strftime(to_format)
                        
                        cursor.execute(
                            f"UPDATE {table_name} SET {date_column} = ? WHERE rowid = ?",
                            [new_date, rowid]
                        )
                        converted_count += 1
                    except Exception:
                        pass  # 跳过无法转换的记录
                        
            conn.commit()
            logger.info(f"日期格式转换完成: {table_name}.{date_column}, 转换 {converted_count} 条")
            
        except Exception as e:
            logger.error(f"日期格式转换失败: {table_name}, {e}")
            conn.rollback()
        finally:
            conn.close()
            
    def create_table_from_template(self, template_table: str, new_table: str):
        """从模板表创建新表
        
        Args:
            template_table: 模板表名
            new_table: 新表名
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 获取模板表结构
            cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{template_table}'")
            create_sql = cursor.fetchone()[0]
            
            # 替换表名
            create_sql = create_sql.replace(template_table, new_table)
            
            # 创建新表
            cursor.execute(create_sql)
            conn.commit()
            
            logger.info(f"从模板创建新表: {new_table}")
            
        except Exception as e:
            logger.error(f"创建新表失败: {new_table}, {e}")
            conn.rollback()
        finally:
            conn.close()
            
    def split_table_by_year(self, table_name: str, date_column: str):
        """按年份拆分表
        
        Args:
            table_name: 表名
            date_column: 日期列名
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 获取所有年份
            cursor.execute(f"""
                SELECT DISTINCT SUBSTR({date_column}, 1, 4) as year 
                FROM {table_name}
                WHERE {date_column} IS NOT NULL
            """)
            years = [row[0] for row in cursor.fetchall()]
            
            for year in years:
                new_table = f'{table_name}_{year}'
                
                # 创建新表
                self.create_table_from_template(table_name, new_table)
                
                # 复制数据
                cursor.execute(f"""
                    INSERT INTO {new_table} 
                    SELECT * FROM {table_name} 
                    WHERE {date_column} LIKE '{year}%'
                """)
                
                logger.info(f"拆分表: {table_name} → {new_table}")
                
            conn.commit()
            logger.info(f"按年份拆分完成: {table_name}, {len(years)} 个年份表")
            
        except Exception as e:
            logger.error(f"按年份拆分失败: {table_name}, {e}")
            conn.rollback()
        finally:
            conn.close()
            
    def migrate_to_sharding(self, source_db: str, target_dbs: Dict[str, str], 
                           table_mapping: Dict[str, str]):
        """迁移到分库架构
        
        Args:
            source_db: 源数据库路径
            target_dbs: 目标数据库字典 {db_name: db_path}
            table_mapping: 表映射 {table_name: db_name}
        """
        source_conn = sqlite3.connect(source_db)
        
        try:
            for table_name, db_name in table_mapping.items():
                target_path = target_dbs.get(db_name)
                if not target_path:
                    logger.warning(f"目标数据库不存在: {db_name}")
                    continue
                    
                target_conn = sqlite3.connect(target_path)
                
                try:
                    # 获取源表数据
                    cursor = source_conn.cursor()
                    cursor.execute(f"SELECT * FROM {table_name}")
                    rows = cursor.fetchall()
                    
                    # 获取列名
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = [row[1] for row in cursor.fetchall()]
                    
                    if rows:
                        # 插入目标表
                        target_cursor = target_conn.cursor()
                        placeholders = ', '.join(['?' for _ in columns])
                        column_names = ', '.join(columns)
                        
                        target_cursor.executemany(
                            f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})",
                            rows
                        )
                        target_conn.commit()
                        
                        logger.info(f"迁移表: {table_name} → {db_name} ({len(rows)} 行)")
                    
                except Exception as e:
                    logger.error(f"迁移表失败: {table_name}, {e}")
                finally:
                    target_conn.close()
                    
        finally:
            source_conn.close()
            
    def get_table_stats(self, table_name: str) -> Dict:
        """获取表统计信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 获取行数
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row_count = cursor.fetchone()[0]
            
            # 获取表大小
            cursor.execute(f"""
                SELECT page_count * page_size 
                FROM pragma_page_count(), pragma_page_size()
            """)
            db_size = cursor.fetchone()[0]
            
            return {
                'table_name': table_name,
                'row_count': row_count,
                'db_size': db_size
            }
            
        except Exception as e:
            logger.error(f"获取表统计失败: {table_name}, {e}")
            return {}
        finally:
            conn.close()


def init_migration(db_path: str) -> Migration:
    """初始化迁移工具"""
    return Migration(db_path)
