import React, { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import ConsoleLayout from './components/ConsoleLayout'
import FileLogsList from './pages/FileLogsList'
import FileLogDetail from './pages/FileLogDetail'
import AudioTestDashboard from './pages/AudioTestDashboard'
import FlowEditor from './pages/FlowEditor'
import Login from './pages/Login'
import ClientManagement from './pages/ClientManagement'
import UserManagement from './pages/UserManagement'
import './App.css'

function App() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const savedUser = localStorage.getItem('user')
    const token = localStorage.getItem('token')
    if (savedUser && token) {
      setUser(JSON.parse(savedUser))
    }
    setLoading(false)
  }, [])

  const handleLoginSuccess = (userData) => {
    setUser(userData)
  }

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    setUser(null)
  }

  if (loading) return null

  if (!user) {
    return <Login onLoginSuccess={handleLoginSuccess} />
  }

  return (
    <BrowserRouter>
      <ConsoleLayout user={user} onLogout={handleLogout}>
        <Routes>
          <Route path="/" element={<Navigate to="/console/file-logs" replace />} />
          <Route path="/console/file-logs" element={<FileLogsList user={user} />} />
          <Route path="/console/file-logs/:clientId/:callId" element={<FileLogDetail />} />
          <Route path="/console/clients" element={<ClientManagement />} />
          <Route path="/console/users" element={<UserManagement />} />
          <Route path="/console/audio-tests" element={<AudioTestDashboard />} />
          <Route path="/console/flow-editor" element={<FlowEditor />} />
        </Routes>
      </ConsoleLayout>
    </BrowserRouter>
  )
}

export default App
