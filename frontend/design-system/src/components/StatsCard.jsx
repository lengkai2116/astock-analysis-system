import React from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { Card } from './Card'

const trendIcons = {
  up: TrendingUp,
  down: TrendingDown,
  neutral: Minus
}

const trendColors = {
  up: 'var(--color-up)',
  down: 'var(--color-down)',
  neutral: 'var(--signal-neutral)'
}

export function StatsCard({ label, value, trend = 'neutral', subtitle, icon: Icon }) {
  const TrendIcon = trendIcons[trend]

  return (
    <Card>
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          {Icon && (
            <div
              className="w-10 h-10 rounded-[10px] flex items-center justify-center"
              style={{ background: 'var(--bg-subtle)' }}
            >
              <Icon size={20} style={{ color: 'var(--text-secondary)' }} />
            </div>
          )}
          <div>
            <div className="text-[14px]" style={{ color: 'var(--text-muted)' }}>
              {label}
            </div>
            <div
              className="text-[32px] font-semibold leading-[1.3] mt-1"
              style={{ color: trendColors[trend] }}
            >
              {value}
            </div>
          </div>
        </div>
        <TrendIcon size={20} style={{ color: trendColors[trend] }} />
      </div>
      {subtitle && (
        <div className="mt-3 text-[12px]" style={{ color: 'var(--text-muted)' }}>
          {subtitle}
        </div>
      )}
    </Card>
  )
}
