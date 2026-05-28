"""
AI策略生成服务
从自然语言描述生成量化策略和指标
支持LLM集成：DeepSeek API、LM Studio本地大模型
"""

import os
import re
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class AIStrategyGenerator:
    """
    AI策略生成器
    
    支持从自然语言描述生成量化指标和策略
    支持的LLM提供商：
    - DeepSeek API (配置: LLM_PROVIDER=deepseek)
    - LM Studio本地大模型 (配置: LLM_PROVIDER=lm_studio)
    - Mock模式 (配置: LLM_PROVIDER=mock, 默认)
    """
    
    def __init__(self, llm_config: Optional[Dict] = None):
        if llm_config is None:
            from app.config import Config
            llm_config = Config.get_llm_config()
        
        self.llm_config = llm_config
        self.llm_type = self.llm_config.get('type', 'mock')
        self.llm_endpoint = self.llm_config.get('endpoint', '')
        self.model_name = self.llm_config.get('model', 'mock')
        self.api_key = self.llm_config.get('api_key', '')
        
        logger.info(f"AI策略生成器初始化，LLM类型: {self.llm_type}, 模型: {self.model_name}")
        
        self.indicator_patterns = {
            'moving_average': {
                'keywords': ['均线', '移动平均', 'MA', 'SMA', 'EMA'],
                'template': 'MA(close, {period})'
            },
            'rsi': {
                'keywords': ['RSI', '相对强弱', '超买', '超卖'],
                'template': 'RSI(close, {period})'
            },
            'macd': {
                'keywords': ['MACD', '指数平滑', '异同移动'],
                'template': 'MACD(close, {fast}, {slow}, {signal})'
            },
            'bollinger': {
                'keywords': ['布林带', 'Bollinger', '波动带'],
                'template': 'BOLL(close, {period}, {std})'
            },
            'kdj': {
                'keywords': ['KDJ', '随机指标', '随机震荡'],
                'template': 'KDJ(close, high, low, {n}, {m1}, {m2})'
            },
            'volume_ratio': {
                'keywords': ['成交量', 'VOL', '量比'],
                'template': 'vol / vol.mean({window})'
            },
            'price_momentum': {
                'keywords': ['动量', 'momentum', 'ROC'],
                'template': '(close - close.shift({period})) / close.shift({period})'
            }
        }
    
    def _call_llm(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """
        调用LLM接口
        
        支持 DeepSeek API 和 LM Studio 格式
        """
        if self.llm_type == 'mock':
            return self._mock_llm_response(prompt)
        
        try:
            import requests
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            # DeepSeek API 需要 API Key
            if self.llm_type == 'deepseek' and self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'
            
            payload = {
                'model': self.model_name,
                'messages': []
            }
            
            if system_prompt:
                payload['messages'].append({
                    'role': 'system',
                    'content': system_prompt
                })
            
            payload['messages'].append({
                'role': 'user',
                'content': prompt
            })
            
            # 兼容不同API格式
            if self.llm_type == 'deepseek':
                endpoint = f'{self.llm_endpoint}/chat/completions'
            else:
                endpoint = f'{self.llm_endpoint}/chat/completions'
            
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                logger.error(f"LLM调用失败: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"LLM调用异常: {str(e)}")
            return None
    
    def _mock_llm_response(self, prompt: str) -> str:
        """模拟LLM响应（用于测试）"""
        if 'RSI' in prompt or '超买' in prompt or '超卖' in prompt:
            return json.dumps({
                'indicator_type': 'rsi',
                'parameters': {'period': 14},
                'formula': 'RSI(close, 14)',
                'description': '相对强弱指标，用于判断超买超卖',
                'signal': '当RSI>70时为超买区域，可能出现回调；当RSI<30时为超卖区域，可能出现反弹'
            }, ensure_ascii=False)
        elif 'MACD' in prompt:
            return json.dumps({
                'indicator_type': 'macd',
                'parameters': {'fast': 12, 'slow': 26, 'signal': 9},
                'formula': 'MACD(close, 12, 26, 9)',
                'description': 'MACD指标，用于判断趋势和动量',
                'signal': 'DIF上穿DEA为金叉买入信号，DIF下穿DEA为死叉卖出信号'
            }, ensure_ascii=False)
        elif '均线' in prompt or 'MA' in prompt:
            return json.dumps({
                'indicator_type': 'moving_average',
                'parameters': {'period': 20},
                'formula': 'MA(close, 20)',
                'description': '简单移动平均线',
                'signal': '价格上穿均线为买入信号，价格下穿均线为卖出信号'
            }, ensure_ascii=False)
        else:
            return json.dumps({
                'indicator_type': 'custom',
                'parameters': {'period': 10},
                'formula': 'MA(close, 10)',
                'description': '自定义移动平均指标',
                'signal': '根据价格与均线的交叉判断买卖时机'
            }, ensure_ascii=False)
    
    def generate_indicator_from_description(self, description: str, 
                                          context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        从自然语言描述生成指标
        
        Args:
            description: 指标描述，例如："当股票RSI指标低于30时买入"
            context: 上下文信息（可选），包含股票代码、时间范围等
        
        Returns:
            生成结果，包含：
            - indicator_type: 指标类型
            - parameters: 指标参数
            - formula: 计算公式
            - description: 指标描述
            - signal: 信号逻辑
            - code_template: 可执行的代码模板
        """
        logger.info(f"开始生成指标: {description}")
        
        indicator_type = self._detect_indicator_type(description)
        parameters = self._extract_parameters(description, indicator_type)
        formula = self._build_formula(indicator_type, parameters)
        signal = self._generate_signal_logic(description, indicator_type, parameters)
        code_template = self._generate_code_template(
            indicator_type, parameters, signal, context
        )
        
        result = {
            'success': True,
            'indicator_type': indicator_type,
            'parameters': parameters,
            'formula': formula,
            'description': self._generate_description(indicator_type, parameters),
            'signal': signal,
            'code_template': code_template,
            'generated_at': datetime.now().isoformat()
        }
        
        logger.info(f"指标生成完成: {indicator_type}")
        return result
    
    def _detect_indicator_type(self, description: str) -> str:
        """检测指标类型"""
        description_lower = description.lower()
        
        for ind_type, pattern in self.indicator_patterns.items():
            for keyword in pattern['keywords']:
                if keyword.lower() in description_lower:
                    return ind_type
        
        if any(word in description_lower for word in ['突破', 'cross']):
            return 'cross_signal'
        elif any(word in description_lower for word in ['背离', 'divergence']):
            return 'divergence'
        elif any(word in description_lower for word in ['量', 'vol']):
            return 'volume_ratio'
        else:
            return 'moving_average'
    
    def _extract_parameters(self, description: str, indicator_type: str) -> Dict:
        """提取指标参数"""
        params = {}
        
        period_match = re.search(r'(\d+)[日周月]', description)
        if period_match:
            params['period'] = int(period_match.group(1))
        elif 'short' in description.lower():
            params['period'] = 5
        elif 'long' in description.lower():
            params['period'] = 20
        else:
            default_periods = {
                'moving_average': 20,
                'rsi': 14,
                'macd': (12, 26, 9),
                'bollinger': (20, 2),
                'kdj': (9, 3, 3)
            }
            params['period'] = default_periods.get(indicator_type, 20)
        
        if indicator_type == 'macd':
            params['fast'] = 12
            params['slow'] = 26
            params['signal'] = 9
        elif indicator_type == 'bollinger':
            params['std'] = 2
        elif indicator_type == 'kdj':
            params['n'] = 9
            params['m1'] = 3
            params['m2'] = 3
        
        threshold_match = re.search(r'[<>]([\d.]+)', description)
        if threshold_match:
            params['threshold'] = float(threshold_match.group(1))
        
        window_match = re.search(r'([\d]+)天|([\d]+)日', description)
        if window_match:
            params['window'] = int(window_match.group(1) or window_match.group(2))
        
        return params
    
    def _build_formula(self, indicator_type: str, parameters: Dict) -> str:
        """构建计算公式"""
        formulas = {
            'moving_average': f"MA(close, {parameters.get('period', 20)})",
            'rsi': f"RSI(close, {parameters.get('period', 14)})",
            'macd': f"MACD(close, {parameters.get('fast', 12)}, {parameters.get('slow', 26)}, {parameters.get('signal', 9)})",
            'bollinger': f"BOLL(close, {parameters.get('period', 20)}, {parameters.get('std', 2)})",
            'kdj': f"KDJ(close, high, low, {parameters.get('n', 9)}, {parameters.get('m1', 3)}, {parameters.get('m2', 3)})",
            'volume_ratio': f"vol / vol.mean({parameters.get('window', 20)})",
            'price_momentum': f"(close - close.shift({parameters.get('period', 10)})) / close.shift({parameters.get('period', 10)})",
            'cross_signal': f"MA(close, {parameters.get('fast', 5)}) - MA(close, {parameters.get('slow', 20)})",
            'divergence': f"(close - close.shift({parameters.get('period', 20)})) / (close.shift({parameters.get('period', 20)}) - close.shift({parameters.get('period', 40)}))"
        }
        
        return formulas.get(indicator_type, formulas['moving_average'])
    
    def _generate_signal_logic(self, description: str, indicator_type: str, 
                              parameters: Dict) -> str:
        """生成信号逻辑"""
        description_lower = description.lower()
        
        if '低于' in description or '< ' in description or '超卖' in description:
            threshold = parameters.get('threshold', 30)
            return f"当指标值 < {threshold}时买入"
        elif '高于' in description or '> ' in description or '超买' in description:
            threshold = parameters.get('threshold', 70)
            return f"当指标值 > {threshold}时卖出"
        elif '金叉' in description or '上穿' in description or 'cross up' in description_lower:
            return f"{parameters.get('fast', 5)}日均线金叉{parameters.get('slow', 20)}日均线时买入"
        elif '死叉' in description or '下穿' in description or 'cross down' in description_lower:
            return f"{parameters.get('fast', 5)}日均线死叉{parameters.get('slow', 20)}日均线时卖出"
        elif '背离' in description:
            return "检测到底背离时买入，检测到顶背离时卖出"
        else:
            threshold = parameters.get('threshold', 0)
            return f"当指标值从下突破{threshold}时买入，从上跌破{threshold}时卖出"
    
    def _generate_code_template(self, indicator_type: str, parameters: Dict,
                               signal: str, context: Optional[Dict]) -> str:
        """生成可执行的代码模板"""
        template = f'''
# {self._generate_description(indicator_type, parameters)}
my_strategy_name = "AI生成的{indicator_type}策略"
my_strategy_description = "{signal}"

# @param period int {parameters.get('period', 20)}
period = {parameters.get('period', 20)}

# 计算指标
indicator = {self._build_formula(indicator_type, parameters)}

# 生成信号
signal = 0
{threshold_logic(parameters)}

return signal
'''
        return template.strip()
    
    def _generate_description(self, indicator_type: str, parameters: Dict) -> str:
        """生成指标描述"""
        descriptions = {
            'moving_average': f"{parameters.get('period', 20)}日均线",
            'rsi': f"{parameters.get('period', 14)}日相对强弱指标(RSI)",
            'macd': f"MACD指标(参数:{parameters.get('fast', 12)},{parameters.get('slow', 26)},{parameters.get('signal', 9)})",
            'bollinger': f"{parameters.get('period', 20)}日布林带(标准差:{parameters.get('std', 2)})",
            'kdj': f"KDJ随机指标(参数:{parameters.get('n', 9)},{parameters.get('m1', 3)},{parameters.get('m2', 3)})",
            'volume_ratio': f"成交量比率(窗口:{parameters.get('window', 20)})",
            'price_momentum': f"价格动量(周期:{parameters.get('period', 10)})",
            'cross_signal': f"均线交叉信号(短:{parameters.get('fast', 5)},长:{parameters.get('slow', 20)})",
            'divergence': f"指标背离检测(周期:{parameters.get('period', 20)})"
        }
        
        return descriptions.get(indicator_type, f"自定义{indicator_type}指标")
    
    def interpret_backtest_result(self, backtest_result: Dict, 
                                 strategy_description: Optional[str] = None) -> Dict[str, Any]:
        """
        AI解读回测结果
        
        Args:
            backtest_result: 回测结果数据
            strategy_description: 策略描述（可选）
        
        Returns:
            AI解读结果，包含：
            - summary: 总体评价
            - strengths: 优势分析
            - weaknesses: 劣势分析
            - suggestions: 改进建议
            - risk_assessment: 风险评估
            - trading_advice: 交易建议
        """
        logger.info("开始AI解读回测结果")
        
        metrics = backtest_result.get('metrics', {})
        trades = backtest_result.get('trades', [])
        
        total_return = metrics.get('total_return', 0)
        sharpe_ratio = metrics.get('sharpe_ratio', 0)
        max_drawdown = metrics.get('max_drawdown', 0)
        win_rate = metrics.get('win_rate', 0)
        total_trades = len(trades)
        
        overall_score = self._calculate_overall_score(
            total_return, sharpe_ratio, max_drawdown, win_rate
        )
        
        strengths = []
        weaknesses = []
        suggestions = []
        
        if total_return > 0.1:
            strengths.append(f"策略盈利能力良好，总收益率为{total_return*100:.2f}%")
        elif total_return > 0:
            strengths.append("策略实现正收益，具有基本的盈利能力")
        else:
            weaknesses.append(f"策略收益为负({total_return*100:.2f}%)，需要优化")
            suggestions.append("建议调整入场时机或优化指标参数")
        
        if sharpe_ratio > 1.5:
            strengths.append(f"风险调整后收益优秀，夏普比率达到{sharpe_ratio:.2f}")
        elif sharpe_ratio > 1:
            strengths.append(f"风险收益比合理，夏普比率为{sharpe_ratio:.2f}")
        else:
            weaknesses.append(f"夏普比率偏低({sharpe_ratio:.2f})，风险收益比不佳")
            suggestions.append("建议增加选股条件或调整仓位管理")
        
        if abs(max_drawdown) < 0.1:
            strengths.append(f"最大回撤控制良好({max_drawdown*100:.2f}%)")
        elif abs(max_drawdown) < 0.2:
            weaknesses.append(f"最大回撤较大({max_drawdown*100:.2f}%)")
            suggestions.append("建议设置止损线或降低单次仓位")
        else:
            weaknesses.append(f"最大回撤严重({max_drawdown*100:.2f}%)，风险较高")
            suggestions.append("强烈建议增加风险控制机制，设置硬止损")
        
        if win_rate > 0.6:
            strengths.append(f"胜率较高({win_rate*100:.1f}%)")
        elif win_rate > 0.5:
            strengths.append(f"胜率适中({win_rate*100:.1f}%)")
        else:
            weaknesses.append(f"胜率偏低({win_rate*100:.1f}%)")
            suggestions.append("建议优化买卖点位或调整止盈止损设置")
        
        if total_trades < 10:
            suggestions.append(f"交易次数较少({total_trades}次)，统计意义有限，建议增加回测周期")
        elif total_trades > 100:
            suggestions.append(f"交易次数充足({total_trades}次)，统计可靠性高")
        
        summary = self._generate_summary(overall_score, total_return, sharpe_ratio, max_drawdown)
        risk_level = self._assess_risk_level(max_drawdown, sharpe_ratio, win_rate)
        trading_advice = self._generate_trading_advice(overall_score, risk_level, suggestions)
        
        result = {
            'success': True,
            'summary': summary,
            'overall_score': overall_score,
            'risk_level': risk_level,
            'strengths': strengths,
            'weaknesses': weaknesses,
            'suggestions': suggestions,
            'detailed_analysis': {
                'profitability': {
                    'score': min(100, max(0, (total_return * 100) + 50)),
                    'total_return': f"{total_return*100:.2f}%",
                    'annual_return': f"{metrics.get('annual_return', 0)*100:.2f}%"
                },
                'risk_adjusted': {
                    'score': min(100, max(0, sharpe_ratio * 50)),
                    'sharpe_ratio': f"{sharpe_ratio:.2f}",
                    'sortino_ratio': f"{metrics.get('sortino_ratio', 0):.2f}"
                },
                'risk_control': {
                    'score': min(100, max(0, 100 - abs(max_drawdown) * 200)),
                    'max_drawdown': f"{max_drawdown*100:.2f}%",
                    'volatility': f"{metrics.get('volatility', 0)*100:.2f}%"
                },
                'consistency': {
                    'score': min(100, max(0, win_rate * 100)),
                    'win_rate': f"{win_rate*100:.1f}%",
                    'total_trades': total_trades,
                    'profit_loss_ratio': f"{metrics.get('profit_loss_ratio', 0):.2f}"
                }
            },
            'trading_advice': trading_advice,
            'generated_at': datetime.now().isoformat()
        }
        
        logger.info(f"回测结果解读完成，总体评分: {overall_score}")
        return result
    
    def _calculate_overall_score(self, total_return: float, sharpe_ratio: float,
                                max_drawdown: float, win_rate: float) -> float:
        """计算综合评分"""
        profit_score = min(100, max(0, total_return * 100 + 50)) * 0.3
        risk_score = min(100, max(0, sharpe_ratio * 50)) * 0.3
        drawdown_score = min(100, max(0, 100 - abs(max_drawdown) * 200)) * 0.2
        win_rate_score = win_rate * 100 * 0.2
        
        return round(profit_score + risk_score + drawdown_score + win_rate_score, 2)
    
    def _generate_summary(self, overall_score: float, total_return: float,
                        sharpe_ratio: float, max_drawdown: float) -> str:
        """生成总体评价"""
        if overall_score >= 80:
            return f"策略表现优秀，综合评分{overall_score}分。总收益率{total_return*100:.2f}%，夏普比率{sharpe_ratio:.2f}，最大回撤{abs(max_drawdown)*100:.2f}%。策略具有较强的盈利能力和良好的风险控制，值得实盘验证。"
        elif overall_score >= 60:
            return f"策略表现良好，综合评分{overall_score}分。总收益率{total_return*100:.2f}%，夏普比率{sharpe_ratio:.2f}。策略基本可行，但仍有优化空间。"
        elif overall_score >= 40:
            return f"策略表现一般，综合评分{overall_score}分。总收益率{total_return*100:.2f}%，最大回撤{abs(max_drawdown)*100:.2f}%。策略需要进一步优化才能实盘使用。"
        else:
            return f"策略表现不佳，综合评分{overall_score}分。总收益率{total_return*100:.2f}%，最大回撤{abs(max_drawdown)*100:.2f}%。建议重新设计策略或调整参数。"
    
    def _assess_risk_level(self, max_drawdown: float, sharpe_ratio: float,
                          win_rate: float) -> str:
        """评估风险等级"""
        risk_score = 0
        
        if abs(max_drawdown) > 0.3:
            risk_score += 3
        elif abs(max_drawdown) > 0.2:
            risk_score += 2
        elif abs(max_drawdown) > 0.1:
            risk_score += 1
        
        if sharpe_ratio < 0.5:
            risk_score += 2
        elif sharpe_ratio < 1:
            risk_score += 1
        
        if win_rate < 0.4:
            risk_score += 2
        elif win_rate < 0.5:
            risk_score += 1
        
        if risk_score >= 5:
            return "高风险"
        elif risk_score >= 3:
            return "中等风险"
        elif risk_score >= 1:
            return "较低风险"
        else:
            return "低风险"
    
    def _generate_trading_advice(self, overall_score: float, risk_level: str,
                               suggestions: List[str]) -> Dict[str, str]:
        """生成交易建议"""
        advice = {
            'suitable_for': '',
            'position_management': '',
            'risk_control': '',
            'next_steps': ''
        }
        
        if overall_score >= 80:
            advice['suitable_for'] = "适合追求稳健收益的投资者，可考虑实盘测试"
            advice['position_management'] = "建议初始仓位30-50%，可根据市场情况适当调整"
            advice['risk_control'] = "设置10-15%的硬止损，必要时进行对冲"
            advice['next_steps'] = "建议进行模拟盘验证1-2个月，然后小资金实盘"
        elif overall_score >= 60:
            advice['suitable_for'] = "适合有一定经验的投资者，需要关注市场变化"
            advice['position_management'] = "建议初始仓位20-30%，逐步建仓"
            advice['risk_control'] = "必须设置止损，建议8-12%的止损线"
            advice['next_steps'] = "建议优化参数后再次回测，然后模拟盘验证"
        elif overall_score >= 40:
            advice['suitable_for'] = "需要进一步优化才能使用"
            advice['position_management'] = "如果一定要使用，建议仓位控制在10-20%"
            advice['risk_control'] = "必须严格止损，建议5-8%的止损线"
            advice['next_steps'] = "建议分析失败原因，调整策略逻辑或参数"
        else:
            advice['suitable_for'] = "不建议使用当前策略"
            advice['position_management'] = "建议使用其他成熟策略"
            advice['risk_control'] = "需要重新设计策略"
            advice['next_steps'] = "建议学习其他有效策略或寻求专业指导"
        
        return advice


def create_strategy_generator(llm_config: Optional[Dict] = None) -> AIStrategyGenerator:
    """创建策略生成器实例"""
    return AIStrategyGenerator(llm_config)
