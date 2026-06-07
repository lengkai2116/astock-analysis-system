import React from 'react'
import { Search } from 'lucide-react'

export function Input({ placeholder, type = 'text', value, onChange, className = '' }) {
  return (
    <input
      type={type}
      className={`input ${className}`}
      placeholder={placeholder}
      value={value}
      onChange={onChange}
    />
  )
}

export function SearchInput({ placeholder = '搜索...', value, onChange }) {
  return (
    <div className="relative inline-flex items-center">
      <Search
        size={16}
        className="absolute left-3 pointer-events-none"
        style={{ color: 'var(--text-muted)' }}
      />
      <input
        type="text"
        className="input input-search"
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        style={{ paddingLeft: '36px' }}
      />
    </div>
  )
}
