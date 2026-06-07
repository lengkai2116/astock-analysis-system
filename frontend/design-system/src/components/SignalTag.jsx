import React from 'react'

const signalLabels = {
  bullish: '看多',
  bearish: '风险',
  watch: '关注',
  neutral: '中性',
  invalid: '失效'
}

export function SignalTag({ type = 'neutral', label }) {
  return (
    <span className={`signal-tag signal-tag-${type}`}>
      <span className={`status-dot status-dot-${type === 'bullish' ? 'up' : type === 'bearish' ? 'down' : type === 'watch' ? 'watch' : 'neutral'}`} />
      {label || signalLabels[type]}
    </span>
  )
}
