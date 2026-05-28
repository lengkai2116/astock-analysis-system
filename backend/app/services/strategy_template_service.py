import re
from typing import Dict, List, Optional
from app import db
from app.models.strategy import StrategyTemplateV2, StrategyTemplateType

class StrategyTemplateService:
    @staticmethod
    def parse_template_code(code: str) -> Dict:
        result = {
            'name': None,
            'description': None,
            'params': []
        }
        
        name_match = re.search(r'my_strategy_name\s*=\s*["\']([^"\']+)["\']', code)
        if name_match:
            result['name'] = name_match.group(1)
        
        desc_match = re.search(r'my_strategy_description\s*=\s*["\']([^"\']+)["\']', code)
        if desc_match:
            result['description'] = desc_match.group(1)
        
        param_pattern = r'#\s*@param\s+(\w+)\s+(\w+)\s+([^\s#]+)\s*(.*)'
        params = re.findall(param_pattern, code)
        
        for name, param_type, default, description in params:
            result['params'].append({
                'name': name,
                'type': param_type,
                'default': default,
                'description': description.strip()
            })
        
        return result
    
    @staticmethod
    def create_template(
        name: str,
        description: str,
        template_type: str,
        code_template: str,
        author: Optional[str] = None,
        is_system: bool = False
    ) -> StrategyTemplateV2:
        parsed = StrategyTemplateService.parse_template_code(code_template)
        
        template = StrategyTemplateV2(
            name=name or parsed.get('name', '未命名策略'),
            description=description or parsed.get('description', ''),
            template_type=StrategyTemplateType(template_type),
            code_template=code_template,
            parameters=parsed.get('params', []),
            is_system=is_system,
            author=author
        )
        
        db.session.add(template)
        db.session.commit()
        return template
    
    @staticmethod
    def get_templates(
        template_type: Optional[str] = None,
        is_system: Optional[bool] = None,
        is_active: bool = True
    ) -> List[StrategyTemplateV2]:
        query = StrategyTemplateV2.query.filter_by(is_active=is_active)
        
        if template_type:
            query = query.filter_by(template_type=StrategyTemplateType(template_type))
        if is_system is not None:
            query = query.filter_by(is_system=is_system)
        
        return query.order_by(StrategyTemplateV2.usage_count.desc()).all()
    
    @staticmethod
    def get_template_by_id(template_id: int) -> Optional[StrategyTemplateV2]:
        return StrategyTemplateV2.query.get(template_id)
    
    @staticmethod
    def update_template(
        template_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        code_template: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Optional[StrategyTemplateV2]:
        template = StrategyTemplateV2.query.get(template_id)
        if not template:
            return None
        
        if name is not None:
            template.name = name
        if description is not None:
            template.description = description
        if code_template is not None:
            template.code_template = code_template
            parsed = StrategyTemplateService.parse_template_code(code_template)
            template.parameters = parsed.get('params', [])
        if is_active is not None:
            template.is_active = is_active
        
        db.session.commit()
        return template
    
    @staticmethod
    def delete_template(template_id: int) -> bool:
        template = StrategyTemplateV2.query.get(template_id)
        if template:
            template.is_active = False
            db.session.commit()
            return True
        return False
    
    @staticmethod
    def increment_usage(template_id: int) -> None:
        template = StrategyTemplateV2.query.get(template_id)
        if template:
            template.usage_count += 1
            db.session.commit()
