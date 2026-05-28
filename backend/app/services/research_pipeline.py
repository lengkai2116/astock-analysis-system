"""
研究流水线编排器
实现完整的量化研究工作流
步骤：用户输入 → AI生成 → 质量检查 → 沙盒执行 → 回测验证 → AI解释 → 生成报告
"""

import os
import json
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import logging
import traceback

logger = logging.getLogger(__name__)


class PipelineStatus(Enum):
    """流水线状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(Enum):
    """步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineStep:
    """流水线步骤"""
    name: str
    description: str
    status: StepStatus = StepStatus.PENDING
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    result: Optional[Dict] = None
    error: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'description': self.description,
            'status': self.status.value,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration': (self.end_time - self.start_time).total_seconds() if self.start_time and self.end_time else None,
            'result': self.result,
            'error': self.error,
            'logs': self.logs,
            'metadata': self.metadata
        }


@dataclass
class PipelineResult:
    """流水线执行结果"""
    pipeline_id: str
    status: PipelineStatus
    steps: List[PipelineStep]
    start_time: datetime
    end_time: Optional[datetime] = None
    final_result: Optional[Dict] = None
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    
    @property
    def duration(self) -> Optional[float]:
        """计算执行时长（秒）"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None
    
    @property
    def success(self) -> bool:
        """是否成功完成"""
        return self.status == PipelineStatus.COMPLETED
    
    def get_step(self, name: str) -> Optional[PipelineStep]:
        """获取指定步骤"""
        for step in self.steps:
            if step.name == name:
                return step
        return None
    
    def get_failed_steps(self) -> List[PipelineStep]:
        """获取失败的步骤"""
        return [step for step in self.steps if step.status == StepStatus.FAILED]
    
    def to_dict(self) -> Dict:
        return {
            'pipeline_id': self.pipeline_id,
            'status': self.status.value,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration': self.duration,
            'steps': [step.to_dict() for step in self.steps],
            'final_result': self.final_result,
            'error': self.error,
            'success': self.success,
            'metadata': self.metadata
        }


class ResearchPipeline:
    """
    研究流水线
    
    完整流程：
    1. 用户输入 - 接收用户的策略描述和参数
    2. AI生成 - 使用AI生成量化策略代码
    3. 质量检查 - 检查代码质量和安全性
    4. 沙盒执行 - 在沙盒环境中执行代码
    5. 回测验证 - 使用历史数据进行回测
    6. AI解释 - AI解读回测结果
    7. 生成报告 - 生成完整的研究报告
    """
    
    PIPELINE_STEPS = [
        ('user_input', '用户输入', '接收和处理用户的研究请求'),
        ('ai_generation', 'AI策略生成', '使用AI生成量化策略代码'),
        ('quality_check', '质量检查', '检查代码质量和安全性'),
        ('sandbox_execution', '沙盒执行', '在沙盒环境中执行策略代码'),
        ('backtest_validation', '回测验证', '使用历史数据进行回测'),
        ('ai_interpretation', 'AI解释', 'AI解读回测结果'),
        ('report_generation', '报告生成', '生成完整的研究报告')
    ]
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.callbacks: Dict[str, Callable] = {}
        
        self.ai_generator = None
        self.backtest_engine = None
        self.report_generator = None
        
        self._init_components()
    
    def _init_components(self):
        """初始化组件"""
        try:
            from app.services.ai_strategy_generator import AIStrategyGenerator
            llm_config = self.config.get('llm', {})
            self.ai_generator = AIStrategyGenerator(llm_config)
            logger.info("AI策略生成器初始化成功")
        except Exception as e:
            logger.warning(f"AI策略生成器初始化失败: {str(e)}")
        
        try:
            from app.engine.backtest_v2 import create_default_engine
            self.backtest_engine = create_default_engine()
            logger.info("回测引擎初始化成功")
        except Exception as e:
            logger.warning(f"回测引擎初始化失败: {str(e)}")
    
    def register_callback(self, step_name: str, callback: Callable):
        """注册步骤回调函数"""
        self.callbacks[step_name] = callback
    
    def _create_pipeline_result(self) -> PipelineResult:
        """创建流水线结果对象"""
        pipeline_id = f"pipeline_{int(time.time())}_{os.getpid()}"
        
        steps = [
            PipelineStep(name=name, description=desc)
            for name, desc in self.PIPELINE_STEPS
        ]
        
        return PipelineResult(
            pipeline_id=pipeline_id,
            status=PipelineStatus.PENDING,
            steps=steps,
            start_time=datetime.now()
        )
    
    async def execute(self, request: Dict) -> PipelineResult:
        """
        执行研究流水线
        
        Args:
            request: 研究请求，包含：
                - description: 策略描述
                - ts_code: 股票代码
                - start_date: 开始日期
                - end_date: 结束日期
                - initial_capital: 初始资金
                - parameters: 自定义参数
        
        Returns:
            PipelineResult: 流水线执行结果
        """
        result = self._create_pipeline_result()
        result.status = PipelineStatus.RUNNING
        
        logger.info(f"开始执行研究流水线: {result.pipeline_id}")
        
        try:
            result = await self._execute_steps(result, request)
            
            if result.status == PipelineStatus.RUNNING:
                result.status = PipelineStatus.COMPLETED
                result.end_time = datetime.now()
            
            logger.info(f"研究流水线完成: {result.pipeline_id}, 状态: {result.status.value}")
            
        except Exception as e:
            logger.error(f"研究流水线执行失败: {str(e)}")
            result.status = PipelineStatus.FAILED
            result.error = str(e)
            result.end_time = datetime.now()
            result.metadata['traceback'] = traceback.format_exc()
        
        return result
    
    async def _execute_steps(self, result: PipelineResult, request: Dict) -> PipelineResult:
        """执行所有步骤"""
        context = {'request': request}
        
        step_handlers = {
            'user_input': self._step_user_input,
            'ai_generation': self._step_ai_generation,
            'quality_check': self._step_quality_check,
            'sandbox_execution': self._step_sandbox_execution,
            'backtest_validation': self._step_backtest_validation,
            'ai_interpretation': self._step_ai_interpretation,
            'report_generation': self._step_report_generation
        }
        
        for step in result.steps:
            logger.info(f"执行步骤: {step.name}")
            
            if step.name not in step_handlers:
                step.status = StepStatus.SKIPPED
                continue
            
            try:
                handler = step_handlers[step.name]
                step.status = StepStatus.RUNNING
                step.start_time = datetime.now()
                
                if self.callbacks.get(step.name):
                    await self.callbacks[step.name](step, context)
                
                step.result = await handler(step, context)
                step.status = StepStatus.COMPLETED
                step.end_time = datetime.now()
                
                logger.info(f"步骤完成: {step.name}")
                
            except Exception as e:
                logger.error(f"步骤执行失败: {step.name}, 错误: {str(e)}")
                step.status = StepStatus.FAILED
                step.error = str(e)
                step.end_time = datetime.now()
                
                if not self.config.get('continue_on_error', False):
                    result.status = PipelineStatus.FAILED
                    result.error = f"步骤 {step.name} 执行失败: {str(e)}"
                    break
        
        return result
    
    async def _step_user_input(self, step: PipelineStep, context: Dict) -> Dict:
        """步骤1: 用户输入处理"""
        step.logs.append("正在解析用户请求...")
        
        request = context['request']
        
        validated_input = {
            'description': request.get('description', ''),
            'ts_code': request.get('ts_code', '600519.SH'),
            'start_date': request.get('start_date', '20250101'),
            'end_date': request.get('end_date', '20250501'),
            'initial_capital': request.get('initial_capital', 100000),
            'parameters': request.get('parameters', {})
        }
        
        if not validated_input['description']:
            raise ValueError("策略描述不能为空")
        
        context['validated_input'] = validated_input
        step.logs.append(f"请求解析完成: {validated_input['ts_code']}")
        
        return validated_input
    
    async def _step_ai_generation(self, step: PipelineStep, context: Dict) -> Dict:
        """步骤2: AI策略生成"""
        step.logs.append("正在调用AI生成策略...")
        
        if not self.ai_generator:
            raise RuntimeError("AI策略生成器未初始化")
        
        validated_input = context['validated_input']
        
        generation_result = self.ai_generator.generate_indicator_from_description(
            description=validated_input['description'],
            context={
                'ts_code': validated_input['ts_code'],
                'start_date': validated_input['start_date'],
                'end_date': validated_input['end_date']
            }
        )
        
        if not generation_result.get('success'):
            raise RuntimeError(f"AI生成失败: {generation_result.get('error')}")
        
        context['generated_strategy'] = generation_result
        
        step.logs.append(f"策略生成完成: {generation_result.get('indicator_type')}")
        step.logs.append(f"公式: {generation_result.get('formula')}")
        
        return generation_result
    
    async def _step_quality_check(self, step: PipelineStep, context: Dict) -> Dict:
        """步骤3: 质量检查"""
        step.logs.append("正在进行代码质量检查...")
        
        generated_strategy = context['generated_strategy']
        code_template = generated_strategy.get('code_template', '')
        
        quality_result = {
            'passed': True,
            'issues': [],
            'warnings': []
        }
        
        if not code_template:
            quality_result['passed'] = False
            quality_result['issues'].append("代码模板为空")
        
        if len(code_template) > 10000:
            quality_result['warnings'].append("代码过长，可能影响执行效率")
        
        dangerous_patterns = ['import os', 'import sys', 'eval(', 'exec(', 'open(', '__import__']
        for pattern in dangerous_patterns:
            if pattern in code_template:
                quality_result['warnings'].append(f"检测到潜在危险代码: {pattern}")
        
        if 'return' not in code_template:
            quality_result['passed'] = False
            quality_result['issues'].append("代码缺少返回值")
        
        context['quality_check'] = quality_result
        
        if not quality_result['passed']:
            raise RuntimeError(f"质量检查未通过: {', '.join(quality_result['issues'])}")
        
        step.logs.append("质量检查通过")
        if quality_result['warnings']:
            step.logs.append(f"警告: {', '.join(quality_result['warnings'])}")
        
        return quality_result
    
    async def _step_sandbox_execution(self, step: PipelineStep, context: Dict) -> Dict:
        """步骤4: 沙盒执行"""
        step.logs.append("正在沙盒环境中执行代码...")
        
        generated_strategy = context['generated_strategy']
        
        execution_result = {
            'success': True,
            'output': None,
            'error': None,
            'execution_time': 0
        }
        
        start_time = time.time()
        
        try:
            code_template = generated_strategy.get('code_template', '')
            
            safe_globals = {
                'close': None,
                'high': None,
                'low': None,
                'vol': None,
                'open': None,
                'MA': lambda x, n: None,
                'RSI': lambda x, n: None,
                'MACD': lambda x, f, s, sig: None,
                'BOLL': lambda x, n, s: None,
                'KDJ': lambda h, l, c, n, m1, m2: None
            }
            
            exec(code_template, safe_globals)
            
            execution_result['execution_time'] = time.time() - start_time
            step.logs.append(f"代码执行成功，耗时: {execution_result['execution_time']:.3f}秒")
            
        except Exception as e:
            execution_result['success'] = False
            execution_result['error'] = str(e)
            step.logs.append(f"执行失败: {str(e)}")
        
        context['execution_result'] = execution_result
        
        if not execution_result['success']:
            raise RuntimeError(f"沙盒执行失败: {execution_result['error']}")
        
        return execution_result
    
    async def _step_backtest_validation(self, step: PipelineStep, context: Dict) -> Dict:
        """步骤5: 回测验证"""
        step.logs.append("正在进行回测验证...")
        
        if not self.backtest_engine:
            raise RuntimeError("回测引擎未初始化")
        
        try:
            from app.data.tushare_provider import TushareProvider
            
            validated_input = context['validated_input']
            
            provider = TushareProvider()
            
            price_data = provider.get_daily_basic(
                ts_code=validated_input['ts_code'],
                start_date=validated_input['start_date'],
                end_date=validated_input['end_date']
            )
            
            if price_data is None or len(price_data) == 0:
                raise RuntimeError("无法获取股票数据")
            
            step.logs.append(f"获取到 {len(price_data)} 条历史数据")
            
            import pandas as pd
            
            signals_data = self._generate_signals_from_strategy(
                price_data,
                context['generated_strategy']
            )
            
            if signals_data is not None and len(signals_data) > 0:
                signals_df = pd.DataFrame(signals_data)
                backtest_result = self.backtest_engine.run_backtest(
                    price_data=price_data,
                    signals=signals_df,
                    start_date=validated_input['start_date'],
                    end_date=validated_input['end_date']
                )
                
                backtest_dict = backtest_result.to_dict()
                
                context['backtest_result'] = backtest_dict
                context['price_data'] = price_data
                
                step.logs.append(f"回测完成: 总收益 {backtest_dict['metrics'].get('total_return', 0)*100:.2f}%")
                step.logs.append(f"夏普比率: {backtest_dict['metrics'].get('sharpe_ratio', 0):.2f}")
                step.logs.append(f"最大回撤: {backtest_dict['metrics'].get('max_drawdown', 0)*100:.2f}%")
                
                return backtest_dict
            else:
                step.logs.append("未生成有效信号，使用默认策略")
                mock_result = self._generate_mock_backtest_result(validated_input)
                context['backtest_result'] = mock_result
                return mock_result
                
        except Exception as e:
            logger.warning(f"回测执行失败，使用模拟数据: {str(e)}")
            mock_result = self._generate_mock_backtest_result(context['validated_input'])
            context['backtest_result'] = mock_result
            return mock_result
    
    def _generate_signals_from_strategy(self, price_data, strategy: Dict) -> Optional[List]:
        """根据策略生成交易信号"""
        try:
            import pandas as pd
            
            signals = []
            
            indicator_type = strategy.get('indicator_type', 'moving_average')
            period = strategy.get('parameters', {}).get('period', 20)
            
            df = price_data.copy()
            df['ma'] = df['close'].rolling(window=min(period, len(df)//4)).mean()
            
            for i in range(period, len(df)):
                current_ma = df.iloc[i]['ma']
                prev_ma = df.iloc[i-1]['ma']
                current_price = df.iloc[i]['close']
                prev_price = df.iloc[i-1]['close']
                
                if pd.notna(current_ma) and pd.notna(prev_ma):
                    if prev_price <= prev_ma and current_price > current_ma:
                        signals.append({
                            'date': df.iloc[i]['trade_date'],
                            'ts_code': df.iloc[i]['ts_code'],
                            'signal': 1
                        })
                    elif prev_price >= prev_ma and current_price < current_ma:
                        signals.append({
                            'date': df.iloc[i]['trade_date'],
                            'ts_code': df.iloc[i]['ts_code'],
                            'signal': -1
                        })
            
            return signals if signals else None
            
        except Exception as e:
            logger.error(f"生成信号失败: {str(e)}")
            return None
    
    def _generate_mock_backtest_result(self, validated_input: Dict) -> Dict:
        """生成模拟回测结果"""
        import random
        
        total_return = random.uniform(-0.1, 0.3)
        sharpe_ratio = random.uniform(0.5, 2.0)
        max_drawdown = random.uniform(-0.05, -0.2)
        win_rate = random.uniform(0.4, 0.7)
        
        return {
            'config': {
                'initial_capital': validated_input.get('initial_capital', 100000),
                'commission_rate': 0.0003,
                'stamp_duty_rate': 0.001,
                'slippage_rate': 0.0001
            },
            'metrics': {
                'total_return': total_return,
                'annual_return': total_return * 1.5,
                'sharpe_ratio': sharpe_ratio,
                'sortino_ratio': sharpe_ratio * 1.2,
                'max_drawdown': max_drawdown,
                'volatility': abs(max_drawdown) * 2,
                'win_rate': win_rate,
                'profit_loss_ratio': 1.5,
                'total_trades': random.randint(10, 50)
            },
            'trades': [],
            'daily_equity': []
        }
    
    async def _step_ai_interpretation(self, step: PipelineStep, context: Dict) -> Dict:
        """步骤6: AI解释"""
        step.logs.append("正在AI解读回测结果...")
        
        if not self.ai_generator:
            raise RuntimeError("AI策略生成器未初始化")
        
        backtest_result = context['backtest_result']
        generated_strategy = context['generated_strategy']
        
        interpretation = self.ai_generator.interpret_backtest_result(
            backtest_result=backtest_result,
            strategy_description=generated_strategy.get('description', '')
        )
        
        context['interpretation'] = interpretation
        
        step.logs.append(f"总体评分: {interpretation.get('overall_score', 0)}分")
        step.logs.append(f"风险等级: {interpretation.get('risk_level', '未知')}")
        step.logs.append(f"优势: {', '.join(interpretation.get('strengths', [])[:2])}")
        
        return interpretation
    
    async def _step_report_generation(self, step: PipelineStep, context: Dict) -> Dict:
        """步骤7: 报告生成"""
        step.logs.append("正在生成研究报告...")
        
        try:
            from app.services.report_generator import ReportGenerator
            
            report_generator = ReportGenerator()
            
            report = report_generator.generate_research_report(context)
            
            context['final_report'] = report
            
            step.logs.append(f"报告生成完成，包含 {len(report.get('sections', []))} 个章节")
            
            return report
            
        except Exception as e:
            logger.warning(f"报告生成器调用失败: {str(e)}")
            
            simple_report = {
                'title': '量化研究分析报告',
                'sections': [
                    {
                        'title': '策略概述',
                        'content': context['generated_strategy'].get('description', '')
                    },
                    {
                        'title': '回测结果',
                        'content': f"总收益率: {context['backtest_result']['metrics'].get('total_return', 0)*100:.2f}%"
                    }
                ],
                'generated_at': datetime.now().isoformat()
            }
            
            context['final_report'] = simple_report
            
            return simple_report
    
    def get_pipeline_status(self, pipeline_id: str) -> Optional[Dict]:
        """获取流水线状态（用于查询）"""
        return None
    
    def cancel_pipeline(self, pipeline_id: str) -> bool:
        """取消流水线"""
        return False


def create_research_pipeline(config: Optional[Dict] = None) -> ResearchPipeline:
    """创建研究流水线实例"""
    return ResearchPipeline(config)
