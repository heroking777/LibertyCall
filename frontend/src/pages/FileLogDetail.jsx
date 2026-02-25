import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import api from '../api'
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
  const [summary, setSummary] = useState(null) // 要約表示用

  useEffect(() => {
    fetchLogDetail()
    
    // 🔹 リアルタイム更新 (SSE)
    const es = new EventSource(`${API_BASE}/calls/stream?id=${callId}`)
    
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        
        // 接続確認メッセージは無視
        if (data.type === 'connected') {
          return
        }
        
        // call_idが一致する場合のみ処理
        if (data.call_id === callId) {
          // 要約更新
          if (data.summary) {
            setSummary(data.summary)
          }
          
          // イベント（会話ログなど）追加
          if (data.event) {
            setLogs(prev => {
              // 重複チェック（同じtimestamp + role + textの組み合わせを避ける）
              const exists = prev.some(
                log => log.timestamp === data.event.timestamp &&
                       log.role === data.event.role &&
                       log.text === data.event.text
              )
              if (exists) {
                return prev
              }
              return [...prev, data.event]
            })
          }
        }
      } catch (err) {
        console.error('Failed to parse SSE message:', err)
      }
    }
    
    es.onerror = (err) => {
      console.warn('[SSE] Connection error:', err)
      // エラー時は接続を閉じて再試行しない（通話終了時などは正常）
    }
    
    return () => {
      es.close()
    }
  }, [clientId, callId])

  const fetchLogDetail = async () => {
    setLoading(true)
    setError(null)
    setLogs([]) // 古いログをクリア（通話が変わったときに前のログが残らないように）
    setCallerNumber(null)
    setStartedAt(null)
    try {
      const response = await api.get(`/logs/${clientId}/${callId}`)
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
    if (!datetime) return ""
    const iso = String(datetime).endsWith("Z") ? datetime : datetime + "Z"
    const d = new Date(iso)
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
  }

  const formatDateTime = (datetime) => {
    if (!datetime) return ''
    const iso = String(datetime).endsWith('Z') ? datetime : datetime + 'Z'
    const d = new Date(iso)
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
          {/* ✅ 要約表示（リアルタイム更新対応） */}
          {summary && (
            <div className="meta-item" style={{ marginTop: '10px', padding: '10px', backgroundColor: '#f5f5f5', borderRadius: '4px' }}>
              <span className="meta-label" style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>要約:</span>
              <span className="meta-value" style={{ display: 'block', color: '#666' }}>{summary}</span>
            </div>
          )}
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

