"""
筹码分布模块测试脚本
用于验证筹码估算和指标计算
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.data.chip_distribution_service import ChipDistributionService, ChipDistributionEstimator
from app.data.chip_indicators import ChipIndicators
from app.data.enhanced_cache_manager import EnhancedCacheManager
from app.data import DataManager
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

def test_estimator():
    """测试筹码估算器"""
    print("="*60)
    print("🧪 测试筹码估算器")
    print("="*60)
    
    # 创建测试数据
    np.random.seed(42)
    n_days = 120
    base_price = 10.0
    
    # 生成模拟日线数据
    dates = pd.date_range(end=datetime.now(), periods=n_days, freq='D')
    price_changes = np.random.normal(0, 0.02, n_days)
    close_prices = base_price * (1 + price_changes).cumprod()
    
    test_data = pd.DataFrame({
        'ts_code': ['000001.SZ'] * n_days,
        'trade_date': dates.date,
        'open': close_prices * (1 - 0.01 * np.random.rand(n_days)),
        'high': close_prices * (1 + 0.02 * np.random.rand(n_days)),
        'low': close_prices * (1 - 0.02 * np.random.rand(n_days)),
        'close': close_prices,
        'vol': 10000000 * np.random.rand(n_days),
        'amount': 100000000 * np.random.rand(n_days)
    })
    
    estimator = ChipDistributionEstimator()
    chip_dist, min_price, max_price, price_step = estimator.estimate(test_data)
    
    print(f"✅ 筹码估算完成！")
    print(f"   价格范围: {min_price:.2f} - {max_price:.2f}")
    print(f"   价格步长: {price_step:.3f}")
    print(f"   价格区间数: {len(chip_dist)}")
    print(f"   筹码分布总和: {chip_dist.sum():.6f}")
    
    if len(chip_dist) > 0:
        max_ratio = chip_dist.max()
        max_idx = chip_dist.argmax()
        print(f"   最大筹码占比: {max_ratio:.4f} (位置: {max_idx})")
    
    return True

def test_chip_service():
    """测试筹码服务"""
    print("\n" + "="*60)
    print("🔧 测试筹码服务")
    print("="*60)
    
    cache = EnhancedCacheManager()
    service = ChipDistributionService(cache_manager=cache)
    
    # 创建测试数据
    np.random.seed(42)
    n_days = 60
    base_price = 15.0
    dates = pd.date_range(end=datetime.now(), periods=n_days, freq='D')
    price_changes = np.random.normal(0, 0.015, n_days)
    close_prices = base_price * (1 + price_changes).cumprod()
    
    test_data = pd.DataFrame({
        'ts_code': ['600519.SH'] * n_days,
        'trade_date': dates.date,
        'open': close_prices * (1 - 0.01 * np.random.rand(n_days)),
        'high': close_prices * (1 + 0.02 * np.random.rand(n_days)),
        'low': close_prices * (1 - 0.02 * np.random.rand(n_days)),
        'close': close_prices,
        'vol': 5000000 * np.random.rand(n_days),
        'amount': 50000000 * np.random.rand(n_days)
    })
    
    result = service.calculate_chip_distribution('600519.SH', test_data)
    
    print(f"✅ 筹码计算完成！")
    print(f"   股票代码: {result['ts_code']}")
    print(f"   交易日期: {result['trade_date']}")
    print(f"   价格区间: {result['price_range']}")
    
    indicators = result['indicators']
    print(f"   SSRP(平均成本): {indicators['ssrp']:.2f}")
    print(f"   筹码集中度: {indicators['concentration']:.4f}")
    print(f"   筹码获利率: {indicators['profit_ratio']:.4f}")
    
    chip_bins = result['chip_bins']
    print(f"   价格区间数量: {len(chip_bins)}")
    
    if len(chip_bins) > 0:
        peaks = [b for b in chip_bins if b['peak_flag']]
        print(f"   检测到筹码峰数量: {len(peaks)}")
        for i, peak in enumerate(peaks[:3]):
            print(f"     峰{i+1}: 价格={peak['price_bin']:.2f}, 占比={peak['chip_ratio']:.4f}")
    
    return True

def test_chip_indicators():
    """测试筹码指标计算器"""
    print("\n" + "="*60)
    print("📊 测试筹码指标计算器")
    print("="*60)
    
    # 创建测试数据
    np.random.seed(42)
    n_bins = 150
    base_price = 12.0
    price_step = 0.1
    
    chip_bins = []
    for i in range(n_bins):
        price = base_price + i * price_step
        ratio = np.random.normal(0, 0.002, 1)[0]
        ratio = max(0, ratio)
        chip_bins.append({
            'price_bin': price,
            'chip_ratio': ratio,
            'accumulated_ratio': 0,
            'peak_flag': False
        })
    
    # 归一化
    total = sum(b['chip_ratio'] for b in chip_bins)
    if total > 0:
        for b in chip_bins:
            b['chip_ratio'] /= total
    
    # 添加两个筹码峰
    peak_indices = [40, 90]
    for idx in peak_indices:
        chip_bins[idx]['chip_ratio'] = 0.03
        chip_bins[idx]['peak_flag'] = True
    
    # 重新归一化
    total = sum(b['chip_ratio'] for b in chip_bins)
    if total > 0:
        for b in chip_bins:
            b['chip_ratio'] /= total
    
    # 计算累计比例
    acc = 0
    for b in chip_bins:
        acc += b['chip_ratio']
        b['accumulated_ratio'] = acc
    
    # 测试指标计算
    indicators = ChipIndicators()
    current_price = base_price + 6.0
    
    all_indicators = indicators.calculate_all_indicators(
        chip_bins,
        current_price
    )
    
    print(f"✅ 指标计算完成！")
    print(f"   当前价格: {current_price:.2f}")
    for key, value in all_indicators.items():
        print(f"   {key}: {value:.4f}" if isinstance(value, float) else f"   {key}: {value}")
    
    # 测试筹码峰检测
    peaks = indicators.find_peak_positions(chip_bins)
    print(f"\n   检测到筹码峰: {len(peaks)}个")
    for i, peak in enumerate(peaks):
        print(f"     峰{i+1}: 价格={peak['price']:.2f}, 占比={peak['ratio']:.4f}")
    
    # 测试支撑阻力位
    levels = indicators.find_support_resistance_levels(chip_bins, threshold=0.01)
    print(f"\n   支撑位数量: {len(levels['support'])}")
    print(f"   阻力位数量: {len(levels['resistance'])}")
    
    return True

def test_integration():
    """测试集成（需要真实数据）"""
    print("\n" + "="*60)
    print("🔗 测试集成（需要Tushare数据）")
    print("="*60)
    
    try:
        data_manager = DataManager()
        
        # 获取一只股票的测试数据
        test_code = '000001.SZ'
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=120)).strftime('%Y-%m-%d')
        
        print(f"📥 获取 {test_code} 的日线数据...")
        daily_data = data_manager.get_cached_daily_data(test_code, start_date, end_date)
        
        if not daily_data.empty:
            print(f"✅ 获得 {len(daily_data)} 条日线数据")
            
            # 测试筹码计算
            cache = EnhancedCacheManager()
            service = ChipDistributionService(cache_manager=cache)
            
            result = service.calculate_chip_distribution(test_code, daily_data)
            print(f"✅ 筹码计算成功！")
            print(f"   SSRP: {result['indicators']['ssrp']:.2f}")
            print(f"   集中度: {result['indicators']['concentration']:.4f}")
            print(f"   获利率: {result['indicators']['profit_ratio']:.4f}")
            
            return True
        else:
            print(f"⚠️ 没有缓存数据，跳过集成测试")
            return True
    except Exception as e:
        print(f"❌ 集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主测试函数"""
    print("\n" + "▓"*60)
    print("▓" + " "*58 + "▓")
    print("▓" + " "*15 + "🎯 筹码分布模块测试" + " "*31 + "▓")
    print("▓" + " "*58 + "▓")
    print("▓"*60 + "\n")
    
    results = []
    
    # 测试1: 筹码估算器
    results.append(("筹码估算器", test_estimator()))
    
    # 测试2: 筹码服务
    results.append(("筹码服务", test_chip_service()))
    
    # 测试3: 筹码指标
    results.append(("筹码指标", test_chip_indicators()))
    
    # 测试4: 集成测试
    results.append(("集成测试", test_integration()))
    
    # 总结
    print("\n" + "="*60)
    print("📋 测试总结")
    print("="*60)
    for name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"   {name}: {status}")
    
    all_passed = all(success for _, success in results)
    
    if all_passed:
        print("\n🎉 所有测试通过！")
    else:
        print("\n⚠️ 部分测试失败，请检查")
    
    return 0 if all_passed else 1

if __name__ == '__main__':
    exit(main())
