import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { API_BASE } from '../config'
import './FlowEditor.css'

function FlowEditor() {
  const [clientId, setClientId] = useState('000')
  const [flowData, setFlowData] = useState('')
  const [originalFlowData, setOriginalFlowData] = useState('')
  const [version, setVersion] = useState('')
  const [updatedAt, setUpdatedAt] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  // 利用可能なクライアントID（将来的にはAPIから取得）
  const availableClientIds = ['000', '001', '002', '003']

  // 初回ロード
  useEffect(() => {
    loadFlowData()
  }, [clientId])

  const loadFlowData = async () => {
    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await axios.get(`${API_BASE}/flow/content`, {
        params: { client_id: clientId }
      })

      setFlowData(response.data.content)
      setOriginalFlowData(response.data.content)
      setVersion(response.data.version)
      setUpdatedAt(response.data.updated_at)
    } catch (err) {
      setError(err.response?.data?.detail || 'フローデータの読み込みに失敗しました')
      console.error('Flow load error:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    // JSON形式の検証
    try {
      JSON.parse(flowData)
    } catch (e) {
      setError(`JSON形式が正しくありません: ${e.message}`)
      return
    }

    setSaving(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await axios.post(
        `${API_BASE}/flow/reload?client_id=${clientId}`,
        { flow_data: flowData },
        {
          headers: {
            'Content-Type': 'application/json'
          }
        }
      )

      setSuccess(`クライアント${clientId}のフローを保存しました。`)
      setOriginalFlowData(flowData)

      // ステータスを再取得してバージョン・更新日時を更新
      const statusResponse = await axios.get(`${API_BASE}/flow/status`, {
        params: { client_id: clientId }
      })
      setVersion(statusResponse.data.version)
      setUpdatedAt(statusResponse.data.updated_at)
    } catch (err) {
      setError(err.response?.data?.detail || '保存に失敗しました')
      console.error('Flow save error:', err)
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    if (window.confirm('編集内容を破棄して元の状態に戻しますか？')) {
      setFlowData(originalFlowData)
      setError(null)
      setSuccess(null)
    }
  }

  const hasChanges = flowData !== originalFlowData

  return (
    <div className="flow-editor-container">
      <div className="flow-editor-header">
        <h1 className="text-2xl font-bold mb-4">会話フローエディタ</h1>

        <div className="flex items-center gap-4 mb-4">
          <div className="flex items-center gap-2">
            <label htmlFor="client-select" className="font-medium">クライアントID:</label>
            <select
              id="client-select"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              className="px-3 py-1 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {availableClientIds.map(id => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
          </div>

          {version && (
            <div className="text-sm text-gray-600">
              <span className="font-medium">バージョン:</span> {version}
            </div>
          )}

          {updatedAt && (
            <div className="text-sm text-gray-600">
              <span className="font-medium">更新日時:</span> {updatedAt}
            </div>
          )}
        </div>
      </div>

      {/* エラー・成功メッセージ */}
      {error && (
        <div className="mb-4 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
          {error}
        </div>
      )}

      {success && (
        <div className="mb-4 p-3 bg-green-100 border border-green-400 text-green-700 rounded">
          {success}
        </div>
      )}

      {/* 編集エリア */}
      <div className="flow-editor-content">
        {loading ? (
          <div className="flex items-center justify-center h-96">
            <div className="text-gray-500">読み込み中...</div>
          </div>
        ) : (
          <>
            <textarea
              value={flowData}
              onChange={(e) => setFlowData(e.target.value)}
              className="w-full h-[60vh] p-4 border border-gray-300 rounded-md font-mono text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="flow.json の内容をここに表示・編集します"
              spellCheck={false}
            />

            {hasChanges && (
              <div className="mt-2 text-sm text-amber-600">
                ⚠️ 未保存の変更があります
              </div>
            )}
          </>
        )}
      </div>

      {/* ボタン */}
      <div className="flow-editor-actions mt-4 flex gap-2">
        <button
          onClick={handleSave}
          disabled={loading || saving || !hasChanges}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
        >
          {saving ? '保存中...' : '保存して再読込'}
        </button>

        <button
          onClick={handleReset}
          disabled={loading || saving || !hasChanges}
          className="px-4 py-2 bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300 disabled:bg-gray-100 disabled:cursor-not-allowed"
        >
          リセット
        </button>

        <button
          onClick={loadFlowData}
          disabled={loading || saving}
          className="px-4 py-2 bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300 disabled:bg-gray-100 disabled:cursor-not-allowed"
        >
          再読み込み
        </button>
      </div>
    </div>
  )
}

export default FlowEditor

