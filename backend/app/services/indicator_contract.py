import re
import ast
from typing import Dict, List, Optional, Any


class IndicatorContractParser:
    @staticmethod
    def parse(code: str) -> Dict[str, Any]:
        result = {
            'success': True,
            'name': None,
            'description': None,
            'parameters': [],
            'outputs': {},
            'errors': []
        }
        
        try:
            tree = ast.parse(code)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            if target.id == 'my_strategy_name':
                                result['name'] = IndicatorContractParser._get_string_value(node.value)
                            elif target.id == 'my_strategy_description':
                                result['description'] = IndicatorContractParser._get_string_value(node.value)
                            elif target.id == 'output':
                                result['outputs'] = IndicatorContractParser._parse_output_dict(node.value)
            
            result['parameters'] = IndicatorContractParser._parse_param_annotations(code)
            
        except SyntaxError as e:
            result['success'] = False
            result['errors'].append(f"语法错误: {str(e)}")
        except Exception as e:
            result['success'] = False
            result['errors'].append(f"解析错误: {str(e)}")
        
        return result
    
    @staticmethod
    def _get_string_value(node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Constant):
            return str(node.value)
        elif isinstance(node, ast.Str):
            return node.s
        return None
    
    @staticmethod
    def _parse_param_annotations(code: str) -> List[Dict[str, Any]]:
        params = []
        pattern = r'@param\s+(\w+)\s*:\s*([\w\[\],\s]+)\s*=\s*(.+)'
        
        matches = re.finditer(pattern, code)
        for idx, match in enumerate(matches, 1):
            param_name = match.group(1)
            param_type = match.group(2).strip()
            param_default = match.group(3).strip()
            
            param_info = {
                'name': param_name,
                'type': IndicatorContractParser._normalize_type(param_type),
                'default': IndicatorContractParser._parse_default_value(param_default),
                'order': idx
            }
            params.append(param_info)
        
        return params
    
    @staticmethod
    def _normalize_type(param_type: str) -> str:
        type_mapping = {
            'int': 'int',
            'float': 'float',
            'str': 'str',
            'bool': 'bool',
            'list[int]': 'int[]',
            'list[float]': 'float[]',
            'list[str]': 'str[]'
        }
        return type_mapping.get(param_type, param_type)
    
    @staticmethod
    def _parse_default_value(default_str: str) -> Any:
        default_str = default_str.strip()
        
        try:
            if default_str in ('True', 'False'):
                return default_str == 'True'
            elif default_str == 'None':
                return None
            elif default_str.startswith('[') and default_str.endswith(']'):
                items = default_str[1:-1].split(',')
                return [item.strip() for item in items if item.strip()]
            elif '.' in default_str and default_str.replace('.', '').isdigit():
                return float(default_str)
            elif default_str.isdigit():
                return int(default_str)
            else:
                return default_str.strip('"\'')
        except:
            return default_str
    
    @staticmethod
    def _parse_output_dict(node: ast.AST) -> Dict[str, Any]:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'output':
                    node = node.value
        
        if isinstance(node, ast.Dict):
            result = {}
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant):
                    result[key.value] = IndicatorContractParser._get_string_value(value)
                elif isinstance(key, ast.Str):
                    result[key.s] = IndicatorContractParser._get_string_value(value)
            return result
        
        return {}
    
    @staticmethod
    def generate_config(parsing_result: Dict[str, Any]) -> Dict[str, Any]:
        config = {
            'name': parsing_result.get('name', 'Unnamed Indicator'),
            'description': parsing_result.get('description', ''),
            'parameters': [],
            'outputs': parsing_result.get('outputs', {})
        }
        
        for param in parsing_result.get('parameters', []):
            param_config = {
                'name': param['name'],
                'type': param['type'],
                'default': param['default'],
                'required': False,
                'label': param['name'].replace('_', ' ').title()
            }
            config['parameters'].append(param_config)
        
        return config
