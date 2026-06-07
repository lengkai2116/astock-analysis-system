import React from 'react'
import { Button } from './Button'

export function PageHeader({ title, description, action, onAction }) {
  return (
    <div className="page-header">
      <div className="page-header-info">
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action && (
        <Button variant="primary" onClick={onAction}>
          {action}
        </Button>
      )}
    </div>
  )
}
