"""
审计日志服务
记录关键操作：登录/登出、策略操作、数据导出等
"""
from datetime import datetime
from flask import request
import json
import logging

logger = logging.getLogger(__name__)

class AuditService:
    """审计日志记录器"""
    
    @staticmethod
    def log(action, result, details=None, user=None):
        """
        记录审计事件
        
        Args:
            action: 操作类型 (login/logout/strategy_save/strategy_delete/data_export)
            result: 结果 (success/failure)
            details: 详情字典 (可选)
            user: 用户标识 (可选)
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "result": result,
            "ip": request.remote_addr if request else "unknown",
            "user_agent": request.headers.get("User-Agent", "") if request else "",
            "user": user or request.headers.get("X-User-Id", "anonymous") if request else "anonymous",
        }
        if details:
            entry["details"] = details
        
        logger.info(f"AUDIT: {json.dumps(entry, ensure_ascii=False)}")
        return entry

    @staticmethod
    def log_login(user, success=True, reason=None):
        return AuditService.log("login", "success" if success else "failure",
                              {"reason": reason} if reason else None, user)
    
    @staticmethod
    def log_logout(user):
        return AuditService.log("logout", "success", None, user)
    
    @staticmethod
    def log_strategy_save(user, strategy_name, strategy_type):
        return AuditService.log("strategy_save", "success",
                              {"name": strategy_name, "type": strategy_type}, user)
    
    @staticmethod
    def log_data_export(user, export_type, count):
        return AuditService.log("data_export", "success",
                              {"export_type": export_type, "count": count}, user)
