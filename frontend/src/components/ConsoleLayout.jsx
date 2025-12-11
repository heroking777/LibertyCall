import React from 'react'
import ConsoleHeader from './ConsoleHeader'
import './ConsoleLayout.css'

function ConsoleLayout({ children }) {
  return (
    <div className="console-layout">
      <ConsoleHeader />
      <main className="console-main">
        {children}
      </main>
    </div>
  )
}

export default ConsoleLayout

