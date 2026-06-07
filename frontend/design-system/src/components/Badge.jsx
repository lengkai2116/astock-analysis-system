import React from 'react'
import { TrendingUp, TrendingDown } from 'lucide-react'

export function Badge({ type = 'up', children }) {
  const icon = type === 'up' ? TrendingUp : TrendingDown
  return (
    <span className={`badge badge-${type}`}>
      {children}
    </span>
  )
}
