import React, { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import api from '../api'

function LiveCallDetail() {
  const { callId } = useParams()
  const navigate = useNavigate()
  const [call, setCall] = useState(null)
  const [logs, setLogs] = useState([])
  const [error, setError] = useState(null)
  const [connected, setConnected] = useState(false)
  const logsEndRef = useRef(null)
  const eventSourceRef = useRef(null)

  useEffect(() => {
    const fetchInitial = async () => {
      try {
        const resp = await api.get(`/live/calls/${callId}`)
        setCall(resp.data.call)
        setLogs(resp.data.logs || [])
      } catch (err) {
        setError(err.response?.data?.detail || '取得に失敗しました')
      }
    }
    fetchInitial()
  }, [callId])

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) return

    const baseUrl = api.defaults.baseURL || ''
    const url = `${baseUrl}/live/calls/${callId}/stream?token=${token}` 

    const es = new EventSource(url)
    eventSourceRef.current = es

    es.onopen = () => setConnected(true)

    es.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data)
        if (parsed.event === 'new_log') {
          setLogs(prev => {
            const exists = prev.some(l => l.id === parsed.data.id)
            if (exists) return prev
            return [...prev, parsed.data]
          })
        } else if (parsed.event === 'call_update') {
          setCall(prev => prev ? { ...prev, ...parsed.data } : prev)
        }
      } catch (e) {
        console.warn('SSE parse error:', e)
      }
    }

    es.onerror = () => {
      setConnected(false)
      es.close()
      setTimeout(() => {
        if (eventSourceRef.current === es) {
          setConnected(false)
        }
      }, 5000)
    }

    return () => {
      es.close()
      eventSourceRef.current = null
    }
  }, [callId])

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const formatTime = (iso) => {
    if (!iso) return ''
    const d = new Date(iso)
    return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  if (error) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center' }}>
        <p style={{ color: '#ef4444' }}>{error}</p>
        <button onClick={() => navigate('/console/live')}
          style={{ marginTop: '1rem', padding: '0.5rem 1rem', backgroundColor: '#3b82f6', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
          戻る
        </button>
      </div>
    )
  }

  return (
    <div style={{ padding: '1.5rem', maxWidth: '800px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <button onClick={() => navigate('/console/live')}
          style={{ padding: '0.5rem 1rem', backgroundColor: '#6b7280', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
          ← 戻る
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: connected ? '#10b981' : '#ef4444', display: 'inline-block' }} />
          <span style={{ fontSize: '0.85rem', color: '#6b7280' }}>{connected ? 'リアルタイム接続中' : '切断'}</span>
        </div>
      </div>

      {call && (
        <div style={{ backgroundColor: 'white', borderRadius: '8px', padding: '1rem', marginBottom: '1rem', boxShadow: '0 1px 3px rgba(0,0,0,0.1)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontWeight: 'bold', fontSize: '1.2rem' }}>{call.caller_number || '番号不明'}</div>
              <div style={{ color: '#6b7280', fontSize: '0.9rem' }}>
                クライアント: {call.client_id} | 開始: {formatTime(call.started_at)}
              </div>
            </div>
            {call.is_transferred && (
              <span style={{ backgroundColor: '#fef3c7', color: '#92400e', padding: '0.25rem 0.75rem', borderRadius: '999px', fontSize: '0.85rem', fontWeight: 'bold', height: 'fit-content' }}>
                転送済み
              </span>
            )}
          </div>
          {call.handover_summary && (
            <div style={{ marginTop: '0.75rem', padding: '0.75rem', backgroundColor: '#fffbeb', borderRadius: '6px', borderLeft: '3px solid #f59e0b' }}>
              <div style={{ fontWeight: 'bold', marginBottom: '0.25rem', color: '#92400e' }}>引き継ぎ要約</div>
              <div style={{ whiteSpace: 'pre-wrap', fontSize: '0.95rem' }}>{call.handover_summary}</div>
            </div>
          )}
        </div>
      )}

      <div style={{ backgroundColor: 'white', borderRadius: '8px', padding: '1rem', boxShadow: '0 1px 3px rgba(0,0,0,0.1)', maxHeight: '60vh', overflowY: 'auto' }}>
        <h3 style={{ margin: '0 0 1rem 0' }}>会話ログ</h3>
        {logs.length === 0 ? (
          <p style={{ textAlign: 'center', color: '#9ca3af' }}>ログがありません</p>
        ) : (
          logs.map((log, i) => (
            <div key={log.id || i} style={{
              display: 'flex', flexDirection: 'column',
              alignItems: log.role === 'user' ? 'flex-end' : 'flex-start',
              marginBottom: '0.75rem',
            }}>
              <div style={{
                maxWidth: '80%', padding: '0.75rem 1rem', borderRadius: '12px',
                backgroundColor: log.role === 'user' ? '#dbeafe' : '#f3f4f6',
                borderBottomRightRadius: log.role === 'user' ? '4px' : '12px',
                borderBottomLeftRadius: log.role === 'user' ? '12px' : '4px',
              }}>
                <div style={{ fontSize: '0.75rem', color: '#6b7280', marginBottom: '0.25rem' }}>
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

export default LiveCallDetail
