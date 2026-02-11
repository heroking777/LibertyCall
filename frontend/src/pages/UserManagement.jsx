import React, { useState, useEffect } from 'react'
import api from '../api'

function UserManagement() {
  const [users, setUsers] = useState([])
  const [clients, setClients] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [editingUser, setEditingUser] = useState(null)
  const [formData, setFormData] = useState({
    email: '',
    password: '',
    role: 'client_admin',
    client_id: ''
  })

  useEffect(() => {
    fetchUsers()
    fetchClients()
  }, [])

  const fetchUsers = async () => {
    try {
      const response = await api.get('/users')
      setUsers(response.data)
    } catch (error) {
      console.error('Failed to fetch users:', error)
    } finally {
      setLoading(false)
    }
  }

  const fetchClients = async () => {
    try {
      const response = await api.get('/clients')
      setClients(response.data)
    } catch (error) {
      console.error('Failed to fetch clients:', error)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      const submitData = { ...formData }
      if (editingUser && !formData.password) {
        delete submitData.password
      }
      
      if (editingUser) {
        await api.put(`/users/${editingUser.id}`, submitData)
      } else {
        await api.post('/users', submitData)
      }
      
      setFormData({ email: '', password: '', role: 'client_admin', client_id: '' })
      setShowCreateForm(false)
      setEditingUser(null)
      fetchUsers()
    } catch (error) {
      console.error('Failed to save user:', error)
      alert(error.response?.data?.detail || '保存に失敗しました')
    }
  }

  const handleEdit = (user) => {
    setEditingUser(user)
    setFormData({
      email: user.email,
      password: '',
      role: user.role,
      client_id: user.client_id || ''
    })
    setShowCreateForm(true)
  }

  const handleDelete = async (user) => {
    if (!confirm(`ユーザー「${user.email}」を削除してもよろしいですか？`)) {
      return
    }
    try {
      await api.delete(`/users/${user.id}`)
      fetchUsers()
    } catch (error) {
      console.error('Failed to delete user:', error)
      alert(error.response?.data?.detail || '削除に失敗しました')
    }
  }

  const handleCancel = () => {
    setFormData({ email: '', password: '', role: 'client_admin', client_id: '' })
    setShowCreateForm(false)
    setEditingUser(null)
  }

  const getRoleText = (role) => {
    switch (role) {
      case 'super_admin':
        return 'スーパー管理者'
      case 'client_admin':
        return 'クライアント管理者'
      default:
        return role
    }
  }

  const getClientName = (clientId) => {
    const client = clients.find(c => c.client_id === clientId)
    return client ? client.name : clientId
  }

  if (loading) {
    return <div style={{ padding: '2rem', textAlign: 'center' }}>読み込み中...</div>
  }

  return (
    <div style={{ padding: '2rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
        <h1>ユーザー管理</h1>
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
          ユーザー追加
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
            <h2>{editingUser ? 'ユーザー編集' : 'ユーザー追加'}</h2>
            <form onSubmit={handleSubmit}>
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>
                  メールアドレス
                </label>
                <input
                  type="email"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
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
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>
                  パスワード{editingUser && '（変更する場合のみ入力）'}
                </label>
                <input
                  type="password"
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  required={!editingUser}
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
                  役割
                </label>
                <select
                  value={formData.role}
                  onChange={(e) => setFormData({ ...formData, role: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    border: '1px solid #d1d5db',
                    borderRadius: '4px',
                    boxSizing: 'border-box'
                  }}
                >
                  <option value="client_admin">クライアント管理者</option>
                  <option value="super_admin">スーパー管理者</option>
                </select>
              </div>
              {formData.role === 'client_admin' && (
                <div style={{ marginBottom: '1.5rem' }}>
                  <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>
                    クライアント
                  </label>
                  <select
                    value={formData.client_id}
                    onChange={(e) => setFormData({ ...formData, client_id: e.target.value })}
                    required
                    style={{
                      width: '100%',
                      padding: '0.5rem',
                      border: '1px solid #d1d5db',
                      borderRadius: '4px',
                      boxSizing: 'border-box'
                    }}
                  >
                    <option value="">選択してください</option>
                    {clients.map((client) => (
                      <option key={client.id} value={client.client_id}>
                        {client.name} ({client.client_id})
                      </option>
                    ))}
                  </select>
                </div>
              )}
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
                  {editingUser ? '更新' : '作成'}
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
              <th style={{ padding: '1rem', textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>メールアドレス</th>
              <th style={{ padding: '1rem', textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>役割</th>
              <th style={{ padding: '1rem', textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>クライアント</th>
              <th style={{ padding: '1rem', textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>状態</th>
              <th style={{ padding: '1rem', textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>作成日</th>
              <th style={{ padding: '1rem', textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id} style={{ borderBottom: '1px solid #e5e7eb' }}>
                <td style={{ padding: '1rem' }}>{user.email}</td>
                <td style={{ padding: '1rem' }}>
                  <span style={{
                    padding: '0.25rem 0.5rem',
                    borderRadius: '4px',
                    fontSize: '0.875rem',
                    backgroundColor: user.role === 'super_admin' ? '#fef3c7' : '#dbeafe',
                    color: user.role === 'super_admin' ? '#92400e' : '#1e40af'
                  }}>
                    {getRoleText(user.role)}
                  </span>
                </td>
                <td style={{ padding: '1rem' }}>
                  {user.client_id ? getClientName(user.client_id) : '-'}
                </td>
                <td style={{ padding: '1rem' }}>
                  <span style={{
                    padding: '0.25rem 0.5rem',
                    borderRadius: '4px',
                    fontSize: '0.875rem',
                    backgroundColor: user.is_active ? '#dcfce7' : '#fee2e2',
                    color: user.is_active ? '#166534' : '#dc2626'
                  }}>
                    {user.is_active ? '有効' : '無効'}
                  </span>
                </td>
                <td style={{ padding: '1rem', color: '#6b7280' }}>
                  {new Date(user.created_at).toLocaleDateString('ja-JP')}
                </td>
                <td style={{ padding: '1rem' }}>
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                      onClick={() => handleEdit(user)}
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
                      onClick={() => handleDelete(user)}
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
        {users.length === 0 && (
          <div style={{ padding: '3rem', textAlign: 'center', color: '#6b7280' }}>
            ユーザーがありません
          </div>
        )}
      </div>
    </div>
  )
}

export default UserManagement
