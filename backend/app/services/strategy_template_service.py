import re
import copy
from typing import Dict, List, Optional
from datetime import datetime
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
        is_system: bool = False,
        **kwargs
    ) -> StrategyTemplateV2:
        parsed = StrategyTemplateService.parse_template_code(code_template)

        template = StrategyTemplateV2(
            name=name or parsed.get('name', '未命名策略'),
            description=description or parsed.get('description', ''),
            template_type=StrategyTemplateType(template_type),
            code_template=code_template,
            parameters=parsed.get('params', []),
            is_system=is_system,
            author=author or kwargs.pop('author', None),
            # A 股扩展字段直接通过 kwargs 传入
            **{k: v for k, v in kwargs.items() if hasattr(StrategyTemplateV2, k)}
        )

        db.session.add(template)
        db.session.commit()
        return template

    @staticmethod
    def get_templates(
        template_type: Optional[str] = None,
        is_system: Optional[bool] = None,
        is_active: bool = True,
        tab: Optional[str] = None,
        cat: Optional[str] = None,
    ) -> List[StrategyTemplateV2]:
        query = StrategyTemplateV2.query.filter_by(is_active=is_active)

        if template_type:
            query = query.filter_by(template_type=StrategyTemplateType(template_type))
        if is_system is not None:
            query = query.filter_by(is_system=is_system)
        if tab == 'system':
            query = query.filter_by(is_system=True)
        elif tab == 'vibe':
            query = query.filter_by(is_system=False)
        if cat:
            query = query.filter_by(cat=cat)

        return query.order_by(StrategyTemplateV2.usage_count.desc()).all()

    @staticmethod
    def get_template_by_id(template_id: int) -> Optional[StrategyTemplateV2]:
        return StrategyTemplateV2.query.get(template_id)

    @staticmethod
    def get_template_by_cat(cat: str) -> Optional[StrategyTemplateV2]:
        """按 cat 字段查找模板（用于详情页 string ID 匹配）"""
        return StrategyTemplateV2.query.filter_by(cat=cat, is_active=True).first()

    @staticmethod
    def update_template(
        template_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        code_template: Optional[str] = None,
        is_active: Optional[bool] = None,
        **kwargs
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

        # A 股扩展字段
        for k, v in kwargs.items():
            if hasattr(template, k) and k not in ('id', 'created_at', 'updated_at'):
                setattr(template, k, v)

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

    @staticmethod
    def clone_template(
        template_id: int,
        author: str = 'user'
    ) -> Optional[StrategyTemplateV2]:
        """克隆系统模板到 Vibe 自建策略"""
        source = StrategyTemplateV2.query.get(template_id)
        if not source:
            return None

        # 复制全部字段，覆盖 is_system/vibe/name
        new_vibe = StrategyTemplateV2(
            name=source.name + '_vibe',
            nameCN=(source.nameCN or source.name) + ' - 自建',
            description=source.description,
            template_type=source.template_type,
            code_template=source.code_template,
            parameters=copy.deepcopy(source.parameters) if source.parameters else None,
            output_schema=copy.deepcopy(source.output_schema) if source.output_schema else None,
            is_system=False,
            is_active=True,
            vibe=True,
            author=author,
            version='1.0.0',
            usage_count=0,
            cat=source.cat or 'vibe',
            catLabel='Vibe自建',
            catCN=source.catCN,
            icon=source.icon,
            tags=copy.deepcopy(source.tags) if source.tags else ['Vibe', '自建'],
            ready=True,
            devLabel=None,
            devPriority=None,
            inputs=copy.deepcopy(source.inputs) if source.inputs else None,
            wiki=copy.deepcopy(source.wiki) if source.wiki else None,
            iconLarge=source.iconLarge,
            updated=datetime.now().strftime('%Y-%m-%d'),
        )

        db.session.add(new_vibe)
        db.session.commit()
        return new_vibe
