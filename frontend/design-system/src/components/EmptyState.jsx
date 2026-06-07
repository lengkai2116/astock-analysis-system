import React from 'react'
import { Button } from './Button'

export function EmptyState({ title, description, action, onAction, icon: Icon }) {
  return (
    <div className="empty-state">
      {Icon && <Icon size={40} style={{ color: 'var(--text-muted)', opacity: 0.5 }} />}
      <div>
        <h3 className="text-[16px] font-medium" style={{ color: 'var(--text-primary)' }}>
          {title}
        </h3>
        <p className="text-[14px] mt-2" style={{ color: 'var(--text-muted)' }}>
          {description}
        </p>
      </div>
      {action && <Button variant="primary" onClick={onAction}>{action}</Button>}
    </div>
  )
}
