import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { API_BASE } from '../config'
import './FileLogDetail.css'

function FileLogDetail() {
  const { clientId, callId } = useParams()
  const navigate = useNavigate()
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [callerNumber, setCallerNumber] = useState(null)
  const [startedAt, setStartedAt] = useState(null)

  useEffect(() => {
    fetchLogDetail()
  }, [clientId, callId])

  const fetchLogDetail = async () => {
    setLoading(true)
    setError(null)
    setLogs([]) // 古いログをクリア（通話が変わったときに前のログが残らないように）
    setCallerNumber(null)
    setStartedAt(null)
    try {
      const response = await axios.get(`${API_BASE}/logs/${clientId}/${callId}`)
      setLogs(response.data.logs || [])
      setCallerNumber(response.data.caller_number || null)
      setStartedAt(response.data.started_at || null)
    } catch (err) {
      console.error('Failed to fetch log detail:', err)
      setError(err.response?.data?.detail || 'ログ詳細の取得に失敗しました')
    } finally {
      setLoading(false)
    }
  }

  const formatTime = (datetime) => {
    const d = new Date(datetime)
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
  }

  const formatDateTime = (datetime) => {
    if (!datetime) return ''
    const d = new Date(datetime)
    return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }

  const displayNumber = (num) => {
    if (!num || num === "-") return "番号不明"
    return num
  }

  return (
    <div className="file-log-detail">
      <div className="file-log-header">
        <button onClick={() => navigate('/console/file-logs')} className="back-btn">
          ← 一覧に戻る
        </button>
        <div className="file-log-title">
          <h2>
            通話ログ詳細: {clientId} / {callId}
          </h2>
          <div className="file-log-meta">
            {startedAt && (
              <div className="meta-item">
                <span className="meta-label">開始日時:</span>
                <span className="meta-value">{formatDateTime(startedAt)}</span>
              </div>
            )}
            <div className="meta-item">
              <span className="meta-label">発信者番号:</span>
              <span className="meta-value">{displayNumber(callerNumber)}</span>
            </div>
          </div>
        </div>
      </div>

      {loading && <div className="loading">読み込み中...</div>}
      {error && <div className="error">{error}</div>}

      {!loading && !error && (
        <div className="log-timeline">
          {logs.length === 0 ? (
            <div className="no-data">ログがありません</div>
          ) : (
            logs.map((log, index) => (
              <div
                key={`${log.timestamp}-${log.role}-${index}`}
                className={`log-entry log-entry-${log.role.toLowerCase()}`}
              >
                <div className="log-time">{formatTime(log.timestamp)}</div>
                <div className="log-content">
                  <div className="log-role">
                    {log.role}
                    {log.role === "AI" && log.template_id && (
                      <span className="log-template">（{log.template_id}）</span>
                    )}
                    :
                  </div>
                  <div className="log-text">{log.text}</div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}

export default FileLogDetail

