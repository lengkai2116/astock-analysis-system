import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
import ast
import time


class IndicatorSandbox:
    def __init__(self, timeout: int = 5, max_memory_mb: int = 100):
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.allowed_modules = {
            'pandas': pd,
            'numpy': np,
            'pd': pd,
            'np': np
        }
        self.forbidden_builtins = {
            'open', 'exec', 'eval', '__import__', 'compile',
            'getattr', 'setattr', 'delattr', 'input', 'print'
        }
    
    def execute(self, code: str, df: Optional[pd.DataFrame] = None, **params) -> Dict[str, Any]:
        start_time = time.time()
        
        if df is None:
            df = self._create_sample_data()
        
        result = {
            'success': False,
            'output': None,
            'error': None,
            'execution_time': 0,
            'memory_usage': 0
        }
        
        try:
            safe_code = self._prepare_safe_code(code)
            
            if not self._validate_code(safe_code):
                result['error'] = '代码包含禁止的操作'
                return result
            
            sandbox_globals = self._create_sandbox_globals(df)
            sandbox_locals = {'df': df, **params}
            
            exec(safe_code, sandbox_globals, sandbox_locals)
            
            execution_time = time.time() - start_time
            
            if execution_time > self.timeout:
                result['error'] = f'执行超时 ({self.timeout}秒)'
                return result
            
            output = sandbox_locals.get('output', {})
            
            if not isinstance(output, dict):
                result['error'] = 'output必须是字典类型'
                return result
            
            result['success'] = True
            result['output'] = output
            result['execution_time'] = execution_time
            result['execution_result'] = sandbox_locals.get('execution_result')
            
        except SyntaxError as e:
            result['error'] = f'语法错误: {str(e)}'
        except NameError as e:
            result['error'] = f'变量未定义: {str(e)}'
        except TypeError as e:
            result['error'] = f'类型错误: {str(e)}'
        except ValueError as e:
            result['error'] = f'值错误: {str(e)}'
        except Exception as e:
            result['error'] = f'执行错误: {str(e)}'
        
        result['execution_time'] = time.time() - start_time
        return result
    
    def _create_sample_data(self) -> pd.DataFrame:
        dates = pd.date_range(start='2023-01-01', periods=100, freq='D')
        return pd.DataFrame({
            'trade_date': dates,
            'open': np.random.uniform(10, 20, 100),
            'high': np.random.uniform(15, 25, 100),
            'low': np.random.uniform(5, 15, 100),
            'close': np.random.uniform(10, 20, 100),
            'vol': np.random.uniform(1000000, 10000000, 100),
            'amount': np.random.uniform(10000000, 100000000, 100)
        })
    
    def _prepare_safe_code(self, code: str) -> str:
        code = code.strip()
        
        if 'def calculate(' not in code:
            if 'def calculate(df' in code:
                pass
            else:
                if 'def calculate(' in code:
                    code = code.replace('def calculate(', 'def calculate(df, ', 1)
                elif code.startswith('def '):
                    lines = code.split('\n')
                    for i, line in enumerate(lines):
                        if line.strip().startswith('def ') and '(' in line:
                            func_name = line.strip().split('(')[0].replace('def ', '')
                            break
                    
                    wrapped_code = f"def calculate(df, **params):\n"
                    for line in lines:
                        wrapped_code += f"    {line}\n"
                    code = wrapped_code
        
        if 'return output' not in code:
            lines = code.split('\n')
            last_indent = 0
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip() and not lines[i].strip().startswith('#'):
                    last_indent = len(lines[i]) - len(lines[i].lstrip())
                    break
            
            code = code.rstrip() + '\n' + ' ' * (last_indent + 4) + 'return output\n'
        
        return code
    
    def _validate_code(self, code: str) -> bool:
        forbidden_patterns = [
            r'import\s+os\b',
            r'import\s+subprocess',
            r'import\s+socket',
            r'import\s+requests',
            r'import\s+urllib',
            r'open\s*\(',
            r'exec\s*\(',
            r'eval\s*\(',
            r'__import__',
            r'os\.system',
            r'os\.popen',
            r'subprocess\.',
            r'\beval\s*\(',
            r'\bcompile\s*\(',
            r'getattr\s*\(',
            r'setattr\s*\(',
            r'delattr\s*\(',
            r'\.read\s*\(',
            r'\.write\s*\(',
            r'\.readlines\s*\(',
            r'\.writelines\s*\(',
        ]
        
        import re
        for pattern in forbidden_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                return False
        
        return True
    
    def _create_sandbox_globals(self, df: pd.DataFrame) -> Dict[str, Any]:
        safe_builtins = {}
        original_builtins = __builtins__ if isinstance(__builtins__, dict) else __builtins__.__dict__
        
        for name in ['abs', 'min', 'max', 'sum', 'len', 'range', 'int', 'float', 'str', 'bool', 'list', 'dict', 'tuple', 'set', 'enumerate', 'zip', 'map', 'filter', 'sorted', 'reversed', 'any', 'all', 'round', 'pow', 'divmod', 'isinstance', 'type']:
            if name in original_builtins:
                safe_builtins[name] = original_builtins[name]
        
        globals_dict = {
            '__builtins__': safe_builtins,
            'pd': pd,
            'pandas': pd,
            'np': np,
            'numpy': np,
            'df': df
        }
        
        return globals_dict
    
    def dry_run(self, code: str) -> Dict[str, Any]:
        return self.execute(code, self._create_sample_data())
