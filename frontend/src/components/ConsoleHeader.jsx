import React, { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import './ConsoleHeader.css'

function ConsoleHeader({ user, onLogout }) {
  const [showUserMenu, setShowUserMenu] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  const handleLogout = () => {
    onLogout()
    navigate('/')
  }

  const isAdmin = user?.role === 'super_admin'

  const adminMenuItems = [
    { path: '/console/file-logs', label: '通話ログ' },
    { path: '/console/live', label: 'ライブ通話' },
    { path: '/console/clients', label: 'クライアント管理' },
    { path: '/console/users', label: 'ユーザー管理' },
    { path: '/console/audio-tests', label: '音声テスト' },
    { path: '/console/flow-editor', label: 'フローエディタ' },
  ]

  const clientAdminMenuItems = [
    { path: '/console/file-logs', label: '通話ログ' },
    { path: '/console/live', label: 'ライブ通話' },
    { path: '/console/audio-tests', label: '音声テスト' },
    { path: '/console/flow-editor', label: 'フローエディタ' },
  ]

  const menuItems = isAdmin ? adminMenuItems : clientAdminMenuItems

  return (
    <header className="site-header">
      <div className="container header-inner">
        <div className="logo-area">
          <div className="logo-mark">LC</div>
          <div className="logo-text">
            <span className="logo-main">LibertyCall</span>
            <span className="logo-sub">AI 電話システム</span>
          </div>
        </div>

        {/* Navigation Menu */}
        <nav className="nav-menu">
          {menuItems.map((item) => (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className={`nav-item ${location.pathname === item.path ? 'active' : ''}`}
            >
              {item.label}
            </button>
          ))}
        </nav>

        {/* User Menu */}
        <div className="user-area">
          <div className="user-info" onClick={() => setShowUserMenu(!showUserMenu)}>
            <span className="user-email">{user?.email}</span>
            <span className="user-role">
              {user?.role === 'super_admin' ? 'スーパー管理者' : 'クライアント管理者'}
            </span>
            <div className="user-avatar">👤</div>
          </div>

          {showUserMenu && (
            <div className="user-dropdown">
              <div className="dropdown-header">
                <div className="dropdown-email">{user?.email}</div>
                <div className="dropdown-role">
                  {user?.role === 'super_admin' ? 'スーパー管理者' : 'クライアント管理者'}
                </div>
              </div>
              <div className="dropdown-divider"></div>
              <button className="dropdown-item logout" onClick={handleLogout}>
                ログアウト
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}

export default ConsoleHeader

