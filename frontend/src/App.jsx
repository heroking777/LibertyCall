import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import ConsoleLayout from './components/ConsoleLayout'
import FileLogsList from './pages/FileLogsList'
import FileLogDetail from './pages/FileLogDetail'
import AudioTestDashboard from './pages/AudioTestDashboard'
import FlowEditor from './pages/FlowEditor'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <ConsoleLayout>
        <Routes>
          <Route path="/" element={<Navigate to="/console/file-logs" replace />} />
          <Route path="/console/file-logs" element={<FileLogsList />} />
          <Route path="/console/file-logs/:clientId/:callId" element={<FileLogDetail />} />
          <Route path="/console/audio-tests" element={<AudioTestDashboard />} />
          <Route path="/console/flow-editor" element={<FlowEditor />} />
        </Routes>
      </ConsoleLayout>
    </BrowserRouter>
  )
}

export default App

