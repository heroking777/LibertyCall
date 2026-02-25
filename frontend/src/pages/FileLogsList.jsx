import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import './FileLogsList.css'

function FileLogsList({ user }) {
  const [calls, setCalls] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [clientId, setClientId] = useState('')
  const [date, setDate] = useState(new Date().toISOString().split('T')[0])
  const navigate = useNavigate()

  // ユーザーの権限に応じてclient_idを設定
  useEffect(() => {
    if (user?.role === 'super_admin') {
      setClientId('000') // スーパー管理者はデフォルトで000
    } else if (user?.role === 'client_admin' && user?.client_id) {
      setClientId(user.client_id) // クライアント管理者は自分のclient_id
    }
  }, [user])

  useEffect(() => {
    if (clientId) {
      fetchCalls()
    }
  }, [clientId, date])

  const fetchCalls = async () => {
    if (!clientId) return
    
    setLoading(true)
    setError(null)
    try {
      // 認証付きAPIを使用
      const [respLogs, respCalls] = await Promise.all([
        api.get('/logs', {
          params: { client_id: clientId, date },
        }),
        api.get('/calls/history', {
          params: { client_id: clientId },
        }),
      ])

      // 既存のログ（AI応答付き通話）
      const logs1 = respLogs.data.calls || respLogs.data.logs || []

      // イベントログ（無音切断など）
      const logs2 = (respCalls.data.calls || []).map(c => ({
        call_id: c.call_id,
        started_at: c.started_at,
        caller_number: c.caller,
        summary: c.event_type === "auto_hangup_silence"
          ? "無音切断（自動）"
          : c.event_type
          ? `イベント: ${c.event_type}`
          : "（イベント）",
      }))

      // logs1 が空の場合は logs2 を表示
      let merged = []
      if (logs1.length === 0) {
        merged = logs2
      } else {
        merged = [...logs1]
        for (const e of logs2) {
          if (!merged.find(l => l.call_id === e.call_id)) {
            merged.push(e)
          }
        }
      }

      // 開始時間降順ソート（UTC統一）
      const toUTC = (dt) => {
        if (!dt) return 0
        return new Date(String(dt).endsWith('Z') ? dt : dt + 'Z').getTime()
      }
      merged.sort((a, b) => toUTC(b.started_at) - toUTC(a.started_at))
      
      setCalls(merged)
    } catch (err) {
      console.error('Failed to fetch calls:', err)
      setError(err.response?.data?.detail || '通話一覧の取得に失敗しました')
    } finally {
      setLoading(false)
    }
  }

  const formatTime = (datetime) => {
    if (!datetime) return '-'
    const isoString = datetime.endsWith('Z') ? datetime : datetime + 'Z'
    const d = new Date(isoString)
    const month = d.getMonth() + 1
    const day = d.getDate()
    const hour = String(d.getHours()).padStart(2, '0')
    const minute = String(d.getMinutes()).padStart(2, '0')
    
    return `${month}/${day} ${hour}:${minute}`  
  }

  const displayNumber = (num) => {
    if (!num || num === "-") return "番号不明"
    return num
  }

  const handleDetailClick = (callId) => {
    navigate(`/console/file-logs/${clientId}/${callId}`)
  }

  return (
    <div className="file-logs-list">
      <div className="file-logs-header">
        <h2>通話ログ一覧</h2>
        <div className="file-logs-filters">
          {user?.role === 'super_admin' && (
            <div className="filter-group">
              <label htmlFor="client-id">クライアントID:</label>
              <input
                id="client-id"
                type="text"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                placeholder="000"
              />
            </div>
          )}
          {user?.role === 'client_admin' && (
            <div className="filter-group">
              <label>クライアントID:</label>
              <div className="client-id-display">{clientId}</div>
            </div>
          )}
          <div className="filter-group">
            <label htmlFor="date">日付:</label>
            <input
              id="date"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>
          <button onClick={fetchCalls} className="refresh-btn" disabled={!clientId}>
            更新
          </button>
        </div>
      </div>

      {loading && <div className="loading">読み込み中...</div>}
      {error && <div className="error">{error}</div>}

      {!loading && !error && (
        <div className="calls-table">
          <table>
            <thead>
              <tr>
                <th>開始時間</th>
                <th>発信者番号</th>
                <th>要約</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {calls.length === 0 ? (
                <tr>
                  <td colSpan="4" className="no-data">
                    該当する通話がありません
                  </td>
                </tr>
              ) : (
                calls.map((call) => (
                  <tr key={call.call_id}>
                    <td>{formatTime(call.started_at)}</td>
                    <td>{displayNumber(call.caller_number)}</td>
                    <td className="summary-cell">{call.summary || '-'}</td>
                    <td>
                      <button
                        onClick={() => handleDetailClick(call.call_id)}
                        className="detail-btn"
                      >
                        詳細
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default FileLogsList

// build 1771835069
