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
    if (!datetime) return '-'
    // UTC時刻をJST（日本時間）に変換して表示
    // ISO文字列がUTCとして解釈されるようにする（Zがない場合は追加）
    const isoString = datetime.endsWith('Z') ? datetime : datetime + 'Z'
    const d = new Date(isoString)
    
    // UTC時刻をJSTに変換（+9時間）
    const jstOffset = 9 * 60 * 60 * 1000 // 9時間をミリ秒に変換
    const jstTime = new Date(d.getTime() + jstOffset)
    
    const month = jstTime.getUTCMonth() + 1
    const day = jstTime.getUTCDate()
    const hour = String(jstTime.getUTCHours()).padStart(2, '0')
    const minute = String(jstTime.getUTCMinutes()).padStart(2, '0')
    
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

