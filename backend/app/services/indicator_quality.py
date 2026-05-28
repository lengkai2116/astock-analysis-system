import ast
import re
from typing import Dict, List, Any


class IndicatorQualityChecker:
    def __init__(self):
        self.issues = []
        self.warnings = []
    
    def check(self, code: str) -> Dict[str, Any]:
        self.issues = []
        self.warnings = []
        
        self._check_syntax(code)
        
        if not self.issues:
            self._check_df_copy(code)
            self._check_future_functions(code)
            self._check_dangerous_operations(code)
            self._check_missing_return(code)
            self._check_common_pitfalls(code)
        
        return {
            'success': len(self.issues) == 0,
            'issues': self.issues,
            'warnings': self.warnings,
            'total_issues': len(self.issues),
            'total_warnings': len(self.warnings)
        }
    
    def _check_syntax(self, code: str):
        try:
            ast.parse(code)
        except SyntaxError as e:
            self.issues.append({
                'type': 'syntax_error',
                'severity': 'error',
                'message': f'语法错误: {str(e)}',
                'line': getattr(e, 'lineno', None),
                'column': getattr(e, 'offset', None)
            })
        except Exception as e:
            self.issues.append({
                'type': 'syntax_error',
                'severity': 'error',
                'message': f'解析错误: {str(e)}',
                'line': None,
                'column': None
            })
    
    def _check_df_copy(self, code: str):
        if 'df.copy()' not in code and 'df = ' in code:
            self.warnings.append({
                'type': 'missing_copy',
                'severity': 'warning',
                'message': '建议在修改DataFrame前使用 df.copy() 避免警告'
            })
    
    def _check_future_functions(self, code: str):
        future_patterns = [
            (r'\.shift\(\s*-\s*\d+\s*\)', 'shift(-N)', '使用未来数据 (shift负数) 可能导致过度拟合'),
            (r'\.shift\(\s*-\s*[a-zA-Z_]\w*\s*\)', 'shift(-var)', '使用未来数据 (shift负数) 可能导致过度拟合'),
            (r'\.iloc\[\s*-\s*\d+\s*:\s*\]', 'iloc[-N:]', '切片使用未来数据可能包含未来信息'),
            (r'\.loc\[.*-.*\]', 'loc with future', '使用未来日期索引可能包含未来信息')
        ]
        
        for pattern, name, message in future_patterns:
            matches = re.finditer(pattern, code)
            for match in matches:
                self.issues.append({
                    'type': 'future_function',
                    'severity': 'error',
                    'name': name,
                    'message': message,
                    'line': code[:match.start()].count('\n') + 1
                })
    
    def _check_dangerous_operations(self, code: str):
        dangerous_patterns = [
            (r'import\s+os\b', 'import os', '禁止导入os模块'),
            (r'import\s+subprocess\b', 'import subprocess', '禁止导入subprocess模块'),
            (r'import\s+socket\b', 'import socket', '禁止导入socket模块'),
            (r'import\s+requests\b', 'import requests', '禁止导入requests模块'),
            (r'import\s+urllib\b', 'import urllib', '禁止导入urllib模块'),
            (r'open\s*\(', 'file open()', '禁止文件操作'),
            (r'exec\s*\(', 'exec()', '禁止使用exec函数'),
            (r'eval\s*\(', 'eval()', '禁止使用eval函数'),
            (r'__import__\s*\(', '__import__()', '禁止使用__import__'),
            (r'os\.system\s*\(', 'os.system()', '禁止执行系统命令'),
            (r'subprocess\.', 'subprocess', '禁止使用子进程'),
            (r'eval\s*\(', 'eval', '禁止使用eval'),
            (r'compile\s*\(', 'compile', '禁止使用compile'),
            (r'getattr\s*\(', 'getattr', '谨慎使用getattr'),
            (r'setattr\s*\(', 'setattr', '谨慎使用setattr'),
            (r'del\s+\w+', 'del statement', '谨慎使用del语句')
        ]
        
        for pattern, name, message in dangerous_patterns:
            matches = re.finditer(pattern, code, re.IGNORECASE)
            for match in matches:
                line_num = code[:match.start()].count('\n') + 1
                
                if name in ['getattr', 'setattr']:
                    severity = 'warning'
                else:
                    severity = 'error'
                
                self.issues.append({
                    'type': 'dangerous_operation',
                    'severity': severity,
                    'name': name,
                    'message': message,
                    'line': line_num
                })
    
    def _check_missing_return(self, code: str):
        try:
            tree = ast.parse(code)
            
            has_output_assign = False
            returns_output = False
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == 'output':
                            has_output_assign = True
                
                if isinstance(node, ast.Return):
                    if isinstance(node.value, ast.Name) and node.value.id == 'output':
                        returns_output = True
            
            if has_output_assign and not returns_output:
                self.warnings.append({
                    'type': 'missing_return',
                    'severity': 'warning',
                    'message': '函数应该返回 output 字典'
                })
        except:
            pass
    
    def _check_common_pitfalls(self, code: str):
        lines = code.split('\n')
        
        for i, line in enumerate(lines, 1):
            if re.search(r'\bfor\s+\w+\s+in\s+range\s*\(\s*\w+\s*,\s*\w+\s*\)', line):
                if i < len(lines) and 'df.iterrows' in lines[i]:
                    self.warnings.append({
                        'type': 'performance',
                        'severity': 'warning',
                        'message': '使用iterrows可能导致性能问题',
                        'line': i
                    })
            
            if 'df[' in line and '.str[' in line:
                self.warnings.append({
                    'type': 'string_operation',
                    'severity': 'warning',
                    'message': '字符串索引操作可能较慢',
                    'line': i
                })
        
        if 'df.fillna' not in code:
            self.warnings.append({
                'type': 'missing_fillna',
                'severity': 'info',
                'message': '建议考虑缺失值处理'
            })
