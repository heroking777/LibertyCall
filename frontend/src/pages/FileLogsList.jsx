import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { API_BASE } from '../config'
import './FileLogsList.css'

function FileLogsList() {
  const [calls, setCalls] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [clientId, setClientId] = useState('000')
  const [date, setDate] = useState(new Date().toISOString().split('T')[0])
  const navigate = useNavigate()

  useEffect(() => {
    fetchCalls()
  }, [clientId, date])

  const fetchCalls = async () => {
    setLoading(true)
    setError(null)
    try {
      // 両方のAPIを並列で取得
      const [respLogs, respCalls] = await Promise.all([
        axios.get(`${API_BASE}/logs`, {
          params: { client_id: clientId, date },
        }),
        axios.get(`${API_BASE}/calls/history`, {
          params: { client_id: clientId },
        }),
      ])

      // 既存のログ（AI応答付き通話）
      const logs1 = respLogs.data.calls || []

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

      // call_id 重複排除（同じ通話が両方にある場合、既存ログを優先）
      const merged = [...logs1]
      for (const e of logs2) {
        if (!merged.find(l => l.call_id === e.call_id)) {
          merged.push(e)
        }
      }

      // 開始時間降順ソート
      merged.sort((a, b) => new Date(b.started_at) - new Date(a.started_at))
      
      setCalls(merged)
    } catch (err) {
      console.error('Failed to fetch calls:', err)
      setError(err.response?.data?.detail || '通話一覧の取得に失敗しました')
    } finally {
      setLoading(false)
    }
  }

  const formatTime = (datetime) => {
    const d = new Date(datetime)
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
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
          <div className="filter-group">
            <label htmlFor="date">日付:</label>
            <input
              id="date"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>
          <button onClick={fetchCalls} className="refresh-btn">
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

