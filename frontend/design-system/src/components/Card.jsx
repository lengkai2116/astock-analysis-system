import React from 'react'

export function Card({ children, className = '', onClick, hoverable = true }) {
  return (
    <div
      className={`card ${onClick ? 'cursor-pointer' : ''} ${className}`}
      onClick={onClick}
      style={{ cursor: onClick ? 'pointer' : undefined }}
    >
      {children}
    </div>
  )
}

export function CardHeader({ title, actions }) {
  return (
    <div className="flex items-center justify-between mb-4">
      <h3 className="text-[20px] font-medium leading-[1.4]" style={{ color: 'var(--text-primary)' }}>
        {title}
      </h3>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function CardBody({ children }) {
  return <div>{children}</div>
}
