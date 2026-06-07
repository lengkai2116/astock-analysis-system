import React, { useState } from 'react'
import {
  LayoutDashboard,
  LineChart,
  Filter,
  Star,
  Bot,
  BarChart3,
  Database,
  FileText,
  FolderOpen,
  Wallet,
  Activity,
  ArrowRight,
  Plus,
  Download,
  RefreshCw,
  Sun,
  Moon,
  Search
} from 'lucide-react'

import { Card, CardHeader } from './components/Card'
import { Button } from './components/Button'
import { StatsCard } from './components/StatsCard'
import { SignalTag } from './components/SignalTag'
import { EmptyState } from './components/EmptyState'
import { Input, SearchInput } from './components/Input'
import { Badge } from './components/Badge'
import { PageHeader } from './components/PageHeader'
import { BlockSection } from './components/BlockSection'

// ============ 模拟数据 ============
const statsData = [
  { label: '自选股总数', value: '128', trend: 'up', subtitle: '上涨 72 只', icon: Star },
  { label: '平均涨跌幅', value: '+3.42%', trend: 'up', subtitle: '72 涨 / 48 跌', icon: Activity },
  { label: '总成交额', value: '3.28亿', trend: 'neutral', subtitle: '截至 14:30', icon: BarChart3 },
  { label: '策略信号', value: '12', trend: 'neutral', subtitle: '7 看多 / 3 风险 / 2 关注', icon: Bot }
]

const signalsData = [
  { stock: '贵州茅台', code: '600519.SH', signal: 'bullish', score: 85, price: '1,850.00', change: '+2.34%', reason: 'MACD 金叉 + 放量突破' },
  { stock: '中国平安', code: '601318.SH', signal: 'watch', score: 62, price: '42.56', change: '+0.87%', reason: '布林带收窄，方向待确认' },
  { stock: '宁德时代', code: '300750.SZ', signal: 'bearish', score: 38, price: '186.20', change: '-1.45%', reason: 'RSI 超买区回落' },
  { stock: '招商银行', code: '600036.SH', signal: 'bullish', score: 78, price: '36.88', change: '+1.12%', reason: '量价齐升，站上20日均线' }
]

const rankData = [
  { rank: 1, name: '贵州茅台', code: '600519.SH', price: '1,850.00', change: '+2.34%', up: true },
  { rank: 2, name: '宁德时代', code: '300750.SZ', price: '186.20', change: '+1.87%', up: true },
  { rank: 3, name: '中国平安', code: '601318.SH', price: '42.56', change: '+0.87%', up: true },
  { rank: 4, name: '招商银行', code: '600036.SH', price: '36.88', change: '+1.12%', up: true },
  { rank: 5, name: '五粮液', code: '000858.SZ', price: '148.60', change: '-0.56%', up: false }
]

function App() {
  const [darkMode, setDarkMode] = useState(true)

  const toggleTheme = () => {
    setDarkMode(!darkMode)
    document.documentElement.classList.toggle('dark')
  }

  return (
    <div className={darkMode ? 'dark' : ''}>
      <div className="min-h-screen transition-colors duration-300" style={{ background: 'var(--bg-page)' }}>
        {/* ===== 侧边栏 ===== */}
        <aside className="fixed left-0 top-0 h-full w-[200px] z-50 flex flex-col"
          style={{ background: 'var(--bg-surface)', borderRight: '1px solid var(--border-default)' }}>
          {/* Logo */}
          <div className="flex items-center gap-3 px-6 py-5"
            style={{ borderBottom: '1px solid var(--border-default)' }}>
            <div className="w-8 h-8 rounded-[10px] flex items-center justify-center"
              style={{ background: 'var(--color-brand-500)' }}>
              <BarChart3 size={16} color="#FFFFFF" />
            </div>
            <span className="text-[16px] font-semibold" style={{ color: 'var(--text-primary)' }}>A股分析</span>
          </div>

          {/* Navigation */}
          <nav className="flex-1 px-3 py-4 space-y-1">
            {[
              { icon: LayoutDashboard, label: '仪表盘', active: true },
              { icon: LineChart, label: '个股策略分析' },
              { icon: Filter, label: '选股系统' },
              { icon: Star, label: '自选监控' },
              { icon: Bot, label: 'AI分析' },
              { icon: BarChart3, label: '回测系统' },
              { icon: Database, label: '因子管理' },
              { icon: FileText, label: '策略模板' },
              { icon: FolderOpen, label: '报告中心' },
              { icon: Wallet, label: '账户管理' }
            ].map((item) => (
              <button
                key={item.label}
                className="flex items-center gap-3 w-full px-3 py-2.5 rounded-[10px] text-[14px] font-medium transition-colors duration-150"
                style={{
                  background: item.active ? 'var(--bg-subtle)' : 'transparent',
                  color: item.active ? 'var(--text-primary)' : 'var(--text-muted)'
                }}
              >
                <item.icon size={20} />
                <span>{item.label}</span>
              </button>
            ))}
          </nav>

          {/* Theme toggle */}
          <div className="px-3 py-4" style={{ borderTop: '1px solid var(--border-default)' }}>
            <button
              className="flex items-center gap-3 w-full px-3 py-2.5 rounded-[10px] text-[14px] font-medium transition-colors duration-150"
              style={{ color: 'var(--text-muted)' }}
              onClick={toggleTheme}
            >
              {darkMode ? <Sun size={20} /> : <Moon size={20} />}
              <span>{darkMode ? '浅色模式' : '深色模式'}</span>
            </button>
          </div>
        </aside>

        {/* ===== 主内容区 ===== */}
        <main className="ml-[200px] min-h-screen">
          <div className="mx-auto" style={{ maxWidth: 'var(--page-max-width)', padding: '32px var(--page-padding-x)' }}>

            {/* ===== PageHeader ===== */}
            <PageHeader
              title="仪表盘"
              description="市场概况与策略信号总览"
              action="刷新数据"
              onAction={() => {}}
            />

            {/* ===== Stats Row ===== */}
            <BlockSection
              title="市场概览"
              description="自选股核心指标汇总"
              action="查看详情"
              onAction={() => {}}
            >
              <div className="grid grid-cols-4 gap-4">
                {statsData.map((stat) => (
                  <StatsCard key={stat.label} {...stat} />
                ))}
              </div>
            </BlockSection>

            {/* ===== Signals Section ===== */}
            <BlockSection
              title="最新策略信号"
              description="基于当前指标触发的策略建议"
              action="查看更多"
              onAction={() => {}}
            >
              <div className="grid grid-cols-4 gap-4">
                {signalsData.map((s) => (
                  <Card key={s.code} hoverable>
                    <div className="flex items-start justify-between mb-3">
                      <div>
                        <div className="text-[16px] font-medium" style={{ color: 'var(--text-primary)' }}>
                          {s.stock}
                        </div>
                        <div className="text-[12px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                          {s.code}
                        </div>
                      </div>
                      <SignalTag type={s.signal} />
                    </div>
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-[14px]" style={{ color: 'var(--text-secondary)' }}>
                        ¥{s.price}
                      </span>
                      <Badge type={s.change.startsWith('+') ? 'up' : 'down'}>
                        {s.change}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-2 mb-3">
                      <div className="flex-1 h-1.5 rounded-full" style={{ background: 'var(--bg-subtle)' }}>
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${s.score}%`,
                            background: s.score >= 70
                              ? 'var(--signal-bullish)'
                              : s.score >= 50
                                ? 'var(--signal-watch)'
                                : 'var(--signal-bearish)'
                          }}
                        />
                      </div>
                      <span className="text-[12px] font-medium" style={{ color: 'var(--text-muted)' }}>
                        {s.score}分
                      </span>
                    </div>
                    <div className="text-[12px]" style={{ color: 'var(--text-muted)' }}>
                      {s.reason}
                    </div>
                  </Card>
                ))}
              </div>
            </BlockSection>

            {/* ===== Rankings + Market ===== */}
            <div className="grid grid-cols-2 gap-4 mb-8">
              {/* 涨跌幅排行 */}
              <Card>
                <CardHeader
                  title="涨跌幅排行"
                  actions={
                    <Button variant="ghost" className="text-[12px]">
                      涨幅榜
                    </Button>
                  }
                />
                <div className="space-y-2">
                  {rankData.map((item) => (
                    <div key={item.code} className="flex items-center gap-3 py-2"
                      style={{ borderBottom: '1px solid var(--border-default)' }}>
                      <span className="w-6 h-6 flex items-center justify-center rounded-full text-[12px] font-medium"
                        style={{
                          background: item.rank <= 3 ? 'var(--text-primary)' : 'var(--bg-subtle)',
                          color: item.rank <= 3 ? 'var(--bg-page)' : 'var(--text-muted)'
                        }}>
                        {item.rank}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-[14px] font-medium truncate" style={{ color: 'var(--text-primary)' }}>
                          {item.name}
                        </div>
                        <div className="text-[12px]" style={{ color: 'var(--text-muted)' }}>
                          {item.code}
                        </div>
                      </div>
                      <div className="text-[14px]" style={{ color: 'var(--text-secondary)' }}>
                        ¥{item.price}
                      </div>
                      <Badge type={item.up ? 'up' : 'down'}>
                        {item.change}
                      </Badge>
                    </div>
                  ))}
                </div>
              </Card>

              {/* 搜索/快捷入口 */}
              <Card>
                <CardHeader title="快捷入口" />
                <div className="space-y-3">
                  <SearchInput placeholder="搜索股票代码或名称..." />
                  <div className="grid grid-cols-2 gap-3 mt-4">
                    {[
                      { icon: Star, label: '自选监控' },
                      { icon: LineChart, label: '指标IDE' },
                      { icon: BarChart3, label: '回测系统' },
                      { icon: Bot, label: 'AI分析' }
                    ].map((item) => (
                      <button key={item.label}
                        className="flex items-center gap-3 p-3 rounded-[10px] text-[14px] font-medium transition-colors duration-150"
                        style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)' }}
                      >
                        <item.icon size={20} style={{ color: 'var(--text-muted)' }} />
                        <span>{item.label}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </Card>
            </div>

            {/* ===== 策略状态 + 资金流向 ===== */}
            <div className="grid grid-cols-2 gap-4 mb-8">
              <Card>
                <CardHeader title="策略状态" />
                <div className="space-y-3">
                  {[
                    { name: '缠论分析', status: 'running' },
                    { name: 'MACD策略', status: 'running' },
                    { name: '布林带策略', status: 'running' },
                    { name: 'RSI策略', status: 'stopped' },
                    { name: '量价策略', status: 'stopped' }
                  ].map((s) => (
                    <div key={s.name} className="flex items-center gap-3 p-2.5 rounded-[10px]"
                      style={{ background: s.status === 'running' ? 'var(--bg-subtle)' : 'transparent' }}>
                      <span className={`status-dot ${s.status === 'running' ? 'status-dot-up' : 'status-dot-neutral'}`} />
                      <span className="flex-1 text-[14px]" style={{ color: 'var(--text-primary)' }}>
                        {s.name}
                      </span>
                      <span className="text-[12px] px-2 py-0.5 rounded-full"
                        style={{
                          background: s.status === 'running' ? 'var(--color-up-bg)' : 'var(--bg-muted)',
                          color: s.status === 'running' ? 'var(--color-up)' : 'var(--text-muted)'
                        }}>
                        {s.status === 'running' ? '运行中' : '已停止'}
                      </span>
                    </div>
                  ))}
                </div>
              </Card>

              <Card>
                <CardHeader
                  title="资金流向"
                  actions={
                    <Button variant="ghost">
                      本周
                    </Button>
                  }
                />
                <div className="space-y-3 pt-2">
                  {[
                    { day: '周一', inflow: 520, outflow: -320 },
                    { day: '周二', inflow: 732, outflow: -582 },
                    { day: '周三', inflow: 801, outflow: -490 },
                    { day: '周四', inflow: 634, outflow: -430 },
                    { day: '周五', inflow: 820, outflow: -350 }
                  ].map((d) => (
                    <div key={d.day} className="flex items-center gap-3">
                      <span className="w-8 text-[12px]" style={{ color: 'var(--text-muted)' }}>{d.day}</span>
                      <div className="flex-1 flex gap-0.5 h-4 items-end">
                        <div
                          className="rounded-sm transition-all"
                          style={{
                            height: `${Math.abs(d.inflow) / 10}px`,
                            width: '40%',
                            background: 'var(--color-up)'
                          }}
                        />
                        <div
                          className="rounded-sm transition-all"
                          style={{
                            height: `${Math.abs(d.outflow) / 10}px`,
                            width: '40%',
                            background: 'var(--color-down)'
                          }}
                        />
                      </div>
                    </div>
                  ))}
                  <div className="flex items-center gap-4 pt-2 text-[12px]" style={{ color: 'var(--text-muted)' }}>
                    <span className="flex items-center gap-1">
                      <span className="w-2 h-2 rounded-sm" style={{ background: 'var(--color-up)' }} />
                      主力流入
                    </span>
                    <span className="flex items-center gap-1">
                      <span className="w-2 h-2 rounded-sm" style={{ background: 'var(--color-down)' }} />
                      主力流出
                    </span>
                  </div>
                </div>
              </Card>
            </div>

            {/* ===== Empty State Demo ===== */}
            <BlockSection
              title="操作记录"
              description="近期策略操作与信号事件"
            >
              <EmptyState
                icon={Activity}
                title="暂无操作记录"
                description="添加自选股并运行策略后，操作记录将在此展示"
                action="前往自选监控"
                onAction={() => {}}
              />
            </BlockSection>

            {/* ===== 组件展示区 ===== */}
            <BlockSection
              title="设计系统组件展示"
              description="信号标签、按钮、徽标等原子组件预览"
            >
              <Card>
                <CardHeader title="信号标签" />
                <div className="flex flex-wrap gap-3">
                  <SignalTag type="bullish" />
                  <SignalTag type="bearish" />
                  <SignalTag type="watch" />
                  <SignalTag type="neutral" />
                  <SignalTag type="invalid" />
                </div>
              </Card>
              <div className="mt-4">
                <Card>
                  <CardHeader title="按钮" />
                  <div className="flex flex-wrap gap-3">
                    <Button variant="primary">主要操作</Button>
                    <Button variant="secondary">次要操作</Button>
                    <Button variant="ghost">文字按钮</Button>
                    <Button variant="danger">风险操作</Button>
                    <Button variant="primary" disabled>禁用状态</Button>
                  </div>
                </Card>
              </div>
            </BlockSection>

            {/* ===== 底部免责 ===== */}
            <div className="py-8 text-center">
              <p className="text-[12px] leading-[1.6]" style={{ color: 'var(--text-muted)' }}>
                本系统输出为策略研究与决策支持信息，不连接券商交易接口，不自动下单，不执行真实资金调仓。所有结论仅供研究参考。
              </p>
            </div>

          </div>
        </main>
      </div>
    </div>
  )
}

export default App
