import React from 'react'
import { Button } from './Button'

export function BlockSection({ title, description, action, onAction, children }) {
  return (
    <div className="block-section">
      <div className="block-section-header">
        <div>
          <h3>{title}</h3>
          {description && <p>{description}</p>}
        </div>
        {action && (
          <Button variant="secondary" onClick={onAction}>
            {action}
          </Button>
        )}
      </div>
      {children}
    </div>
  )
}
