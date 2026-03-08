import React, { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import api from '../api'

const API_BASE = api.defaults.baseURL || ''

function FileLogDetail() {
  const { clientId, callId } = useParams()
  const navigate = useNavigate()
  const [call, setCall] = useState(null)
  const [logs, setLogs] = useState([])
  const [error, setError] = useState(null)
  const logsEndRef = useRef(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        // 通話情報取得
        const callResp = await api.get(`/live/calls/${callId}`)
        setCall(callResp.data.call)
        // ログ取得（DB版）
        const logsResp = await api.get(`/calls/${callId}/logs`)
        setLogs(logsResp.data.data || [])
      } catch (err) {
        // live APIにない場合はlogsだけ取得
        try {
          const logsResp = await api.get(`/calls/${callId}/logs`)
          setLogs(logsResp.data.data || [])
        } catch (err2) {
          setError('取得に失敗しました')
        }
      }
    }
    fetchData()
  }, [callId])

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const formatTime = (iso) => {
    if (!iso) return ''
    const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
    return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  if (error) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center' }}>
        <p style={{ color: '#ef4444' }}>{error}</p>
        <button onClick={() => navigate('/console/file-logs')} style={{ marginTop: '1rem', padding: '0.5rem 1rem', cursor: 'pointer' }}>← 一覧に戻る</button>
      </div>
    )
  }

  return (
    <div style={{ padding: '1.5rem', maxWidth: '800px', margin: '0 auto' }}>
      <button onClick={() => navigate('/console/file-logs')} style={{ background: 'none', border: 'none', color: '#3b82f6', cursor: 'pointer', fontSize: '1rem', marginBottom: '1rem' }}>← 一覧に戻る</button>

      <h2 style={{ fontSize: '1.3rem', marginBottom: '1rem' }}>
        通話ログ詳細: {clientId} / {callId}
      </h2>

      {call && (
        <div style={{ background: '#f9fafb', padding: '1rem', borderRadius: '8px', marginBottom: '1rem', fontSize: '0.9rem' }}>
          <div><strong>開始日時:</strong> {formatTime(call.started_at)}</div>
          <div><strong>発信者番号:</strong> {call.caller_number || '不明'}</div>
        </div>
      )}

      <div style={{ marginBottom: '1rem' }}>
        <strong>録音:</strong>
        <audio controls style={{ width: '100%', marginTop: '0.5rem' }}>
          <source src={`${API_BASE}/logs/${clientId}/${callId}/recording`} type="audio/wav" />
        </audio>
      </div>

      <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '1rem', minHeight: '300px', maxHeight: '500px', overflowY: 'auto' }}>
        {logs.length === 0 ? (
          <p style={{ color: '#9ca3af', textAlign: 'center' }}>ログがありません</p>
        ) : (
          logs.map((log, index) => (
            <div
              key={`${log.timestamp}-${log.role}-${index}`}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: log.role === 'user' ? 'flex-end' : 'flex-start',
                marginBottom: '0.75rem',
              }}
            >
              <div style={{
                maxWidth: '75%',
                padding: '0.5rem 0.75rem',
                borderRadius: '12px',
                backgroundColor: log.role === 'user' ? '#dbeafe' : '#f3f4f6',
                borderBottomRightRadius: log.role === 'user' ? '4px' : '12px',
                borderBottomLeftRadius: log.role === 'user' ? '12px' : '4px',
              }}>
                <div style={{ fontSize: '0.7rem', color: '#6b7280', marginBottom: '0.25rem' }}>
                  {log.role === 'user' ? 'ユーザー' : 'AI'} {formatTime(log.timestamp)}
                </div>
                <div style={{ fontSize: '0.95rem' }}>{log.text}</div>
              </div>
            </div>
          ))
        )}
        <div ref={logsEndRef} />
      </div>
    </div>
  )
}

export default FileLogDetail
