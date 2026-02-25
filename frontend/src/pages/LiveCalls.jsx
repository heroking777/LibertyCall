import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'

function LiveCalls({ user }) {
  const [calls, setCalls] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const navigate = useNavigate()

  const fetchActiveCalls = async () => {
    try {
      const resp = await api.get('/live/active')
      setCalls(resp.data.calls || [])
      setError(null)
    } catch (err) {
      setError(err.response?.data?.detail || '取得に失敗しました')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchActiveCalls()
    const interval = setInterval(fetchActiveCalls, 5000)
    return () => clearInterval(interval)
  }, [])

  const formatTime = (iso) => {
    if (!iso) return '-'
    const isoStr = iso.endsWith('Z') ? iso : iso + 'Z'
    const d = new Date(isoStr)
    return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  return (
    <div style={{ padding: '1.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h2 style={{ margin: 0 }}>アクティブ通話</h2>
        <button onClick={fetchActiveCalls}
          style={{ padding: '0.5rem 1rem', backgroundColor: '#3b82f6', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
          更新
        </button>
      </div>

      {loading && <p>読み込み中...</p>}
      {error && <p style={{ color: '#ef4444' }}>{error}</p>}

      {!loading && calls.length === 0 && (
        <div style={{ textAlign: 'center', padding: '3rem', backgroundColor: '#f9fafb', borderRadius: '8px', color: '#6b7280' }}>
          <p style={{ fontSize: '1.2rem' }}>現在アクティブな通話はありません</p>
          <p>通話が開始されると、ここに表示されます</p>
        </div>
      )}

      {calls.length > 0 && (
        <div style={{ display: 'grid', gap: '1rem' }}>
          {calls.map((call) => (
            <div key={call.call_id}
              onClick={() => navigate(`/console/live/${call.call_id}`)}
              style={{
                padding: '1rem 1.5rem', backgroundColor: 'white', borderRadius: '8px',
                boxShadow: '0 1px 3px rgba(0,0,0,0.1)', cursor: 'pointer',
                borderLeft: call.is_transferred ? '4px solid #f59e0b' : '4px solid #10b981',
                transition: 'box-shadow 0.2s',
              }}
              onMouseEnter={(e) => e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)'}
              onMouseLeave={(e) => e.currentTarget.style.boxShadow = '0 1px 3px rgba(0,0,0,0.1)'}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>
                    {call.caller_number || '番号不明'}
                  </div>
                  <div style={{ color: '#6b7280', fontSize: '0.9rem', marginTop: '0.25rem' }}>
                    クライアント: {call.client_id} | 開始: {formatTime(call.started_at)}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  {call.is_transferred ? (
                    <span style={{ backgroundColor: '#fef3c7', color: '#92400e', padding: '0.25rem 0.75rem', borderRadius: '999px', fontSize: '0.85rem', fontWeight: 'bold' }}>
                      転送済み
                    </span>
                  ) : (
                    <span style={{ backgroundColor: '#d1fae5', color: '#065f46', padding: '0.25rem 0.75rem', borderRadius: '999px', fontSize: '0.85rem', fontWeight: 'bold' }}>
                      通話中
                    </span>
                  )}
                </div>
              </div>
              {call.handover_summary && (
                <div style={{ marginTop: '0.5rem', padding: '0.5rem', backgroundColor: '#fffbeb', borderRadius: '4px', fontSize: '0.9rem', color: '#92400e' }}>
                  {call.handover_summary}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default LiveCalls
