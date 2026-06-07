import React from 'react'

export function Button({
  children,
  variant = 'primary',
  size = 'default',
  disabled = false,
  onClick,
  className = '',
  ...props
}) {
  const variants = {
    primary: 'btn-primary',
    secondary: 'btn-secondary',
    ghost: 'btn-ghost',
    danger: 'btn-danger'
  }

  return (
    <button
      className={`btn ${variants[variant]} ${className}`}
      disabled={disabled}
      onClick={onClick}
      {...props}
    >
      {children}
    </button>
  )
}
