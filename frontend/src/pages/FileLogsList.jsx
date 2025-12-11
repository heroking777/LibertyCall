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
      const response = await axios.get(`${API_BASE}/logs`, {
        params: {
          client_id: clientId,
          date: date,
        },
      })
      setCalls(response.data.calls || [])
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

