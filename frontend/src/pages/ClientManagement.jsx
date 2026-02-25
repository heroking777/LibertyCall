import React, { useState, useEffect } from 'react'
import api from '../api'

function ClientManagement() {
  const [clients, setClients] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [editingClient, setEditingClient] = useState(null)
  const [formData, setFormData] = useState({
    client_id: '',
    name: '',
    description: ''
  })

  useEffect(() => {
    fetchClients()
  }, [])

  const fetchClients = async () => {
    try {
      const response = await api.get('/clients')
      setClients(response.data.clients || response.data || [])
    } catch (error) {
      console.error('Failed to fetch clients:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      if (editingClient) {
        await api.put(`/clients/${editingClient.client_id}`, formData)
      } else {
        await api.post('/clients', formData)
      }
      setFormData({ client_id: '', name: '', description: '' })
      setShowCreateForm(false)
      setEditingClient(null)
      fetchClients()
    } catch (error) {
      console.error('Failed to save client:', error)
      alert(error.response?.data?.detail || '保存に失敗しました')
    }
  }

  const handleEdit = (client) => {
    setEditingClient(client)
    setFormData({
      client_id: client.client_id,
      name: client.name,
      description: client.description || ''
    })
    setShowCreateForm(true)
  }

  const handleDelete = async (client) => {
    if (!confirm(`クライアント「${client.name}」を削除してもよろしいですか？`)) {
      return
    }
    try {
      await api.delete(`/clients/${client.client_id}`)
      fetchClients()
    } catch (error) {
      console.error('Failed to delete client:', error)
      alert(error.response?.data?.detail || '削除に失敗しました')
    }
  }

  const handleCancel = () => {
    setFormData({ client_id: '', name: '', description: '' })
    setShowCreateForm(false)
    setEditingClient(null)
  }

  if (loading) {
    return <div style={{ padding: '2rem', textAlign: 'center' }}>読み込み中...</div>
  }

  return (
    <div style={{ padding: '2rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
        <h1>クライアント管理</h1>
        <button
          onClick={() => setShowCreateForm(true)}
          style={{
            padding: '0.5rem 1rem',
            backgroundColor: '#3b82f6',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer'
          }}
        >
          クライアント追加
        </button>
      </div>

      {showCreateForm && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.5)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 1000
        }}>
          <div style={{
            backgroundColor: 'white',
            padding: '2rem',
            borderRadius: '8px',
            width: '100%',
            maxWidth: '500px'
          }}>
            <h2>{editingClient ? 'クライアント編集' : 'クライアント追加'}</h2>
            <form onSubmit={handleSubmit}>
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>
                  クライアントID
                </label>
                <input
                  type="text"
                  value={formData.client_id}
                  onChange={(e) => setFormData({ ...formData, client_id: e.target.value })}
                  required
                  disabled={!!editingClient}
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    border: '1px solid #d1d5db',
                    borderRadius: '4px',
                    boxSizing: 'border-box'
                  }}
                />
              </div>
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>
                  クライアント名
                </label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  required
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    border: '1px solid #d1d5db',
                    borderRadius: '4px',
                    boxSizing: 'border-box'
                  }}
                />
              </div>
              <div style={{ marginBottom: '1.5rem' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>
                  説明
                </label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  rows={3}
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    border: '1px solid #d1d5db',
                    borderRadius: '4px',
                    boxSizing: 'border-box',
                    resize: 'vertical'
                  }}
                />
              </div>
              <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  onClick={handleCancel}
                  style={{
                    padding: '0.5rem 1rem',
                    backgroundColor: '#6b7280',
                    color: 'white',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer'
                  }}
                >
                  キャンセル
                </button>
                <button
                  type="submit"
                  style={{
                    padding: '0.5rem 1rem',
                    backgroundColor: '#3b82f6',
                    color: 'white',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer'
                  }}
                >
                  {editingClient ? '更新' : '作成'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div style={{ backgroundColor: 'white', borderRadius: '8px', overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.1)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead style={{ backgroundColor: '#f9fafb' }}>
            <tr>
              <th style={{ padding: '1rem', textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>クライアントID</th>
              <th style={{ padding: '1rem', textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>クライアント名</th>
              <th style={{ padding: '1rem', textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>説明</th>
              <th style={{ padding: '1rem', textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>状態</th>
              <th style={{ padding: '1rem', textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>作成日</th>
              <th style={{ padding: '1rem', textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {clients.map((client) => (
              <tr key={client.id} style={{ borderBottom: '1px solid #e5e7eb' }}>
                <td style={{ padding: '1rem' }}>{client.client_id}</td>
                <td style={{ padding: '1rem' }}>{client.name}</td>
                <td style={{ padding: '1rem', color: '#6b7280' }}>{client.description || '-'}</td>
                <td style={{ padding: '1rem' }}>
                  <span style={{
                    padding: '0.25rem 0.5rem',
                    borderRadius: '4px',
                    fontSize: '0.875rem',
                    backgroundColor: client.is_active ? '#dcfce7' : '#fee2e2',
                    color: client.is_active ? '#166534' : '#dc2626'
                  }}>
                    {client.is_active ? '有効' : '無効'}
                  </span>
                </td>
                <td style={{ padding: '1rem', color: '#6b7280' }}>
                  {new Date(client.created_at).toLocaleDateString('ja-JP')}
                </td>
                <td style={{ padding: '1rem' }}>
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                      onClick={() => handleEdit(client)}
                      style={{
                        padding: '0.25rem 0.5rem',
                        backgroundColor: '#3b82f6',
                        color: 'white',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '0.875rem'
                      }}
                    >
                      編集
                    </button>
                    <button
                      onClick={() => handleDelete(client)}
                      style={{
                        padding: '0.25rem 0.5rem',
                        backgroundColor: '#ef4444',
                        color: 'white',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '0.875rem'
                      }}
                    >
                      削除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {clients.length === 0 && (
          <div style={{ padding: '3rem', textAlign: 'center', color: '#6b7280' }}>
            クライアントがありません
          </div>
        )}
      </div>
    </div>
  )
}

export default ClientManagement
