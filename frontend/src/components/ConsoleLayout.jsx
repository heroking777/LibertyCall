import React from 'react'
import ConsoleHeader from './ConsoleHeader'
import './ConsoleLayout.css'

function ConsoleLayout({ children, user, onLogout }) {
  return (
    <div className="console-layout">
      <ConsoleHeader user={user} onLogout={onLogout} />
      <main className="console-main">
        {children}
      </main>
    </div>
  )
}

export default ConsoleLayout

