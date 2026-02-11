import React, { useState } from 'react'
import axios from 'axios'
import { API_BASE } from '../config'

function Login({ onLoginSuccess }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const resp = await axios.post(`${API_BASE}/auth/login`, { email, password })
      const { access_token, user } = resp.data
      localStorage.setItem('token', access_token)
      localStorage.setItem('user', JSON.stringify(user))
      onLoginSuccess(user)
    } catch (err) {
      setError(err.response?.data?.detail || 'ログインに失敗しました')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display:'flex', justifyContent:'center', alignItems:'center', minHeight:'100vh', backgroundColor:'#f3f4f6' }}>
      <div style={{ backgroundColor:'white', padding:'2rem', borderRadius:'8px', boxShadow:'0 2px 10px rgba(0,0,0,0.1)', width:'100%', maxWidth:'400px' }}>
        <h2 style={{ textAlign:'center', marginBottom:'1.5rem' }}>LibertyCall 管理画面</h2>
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom:'1rem' }}>
            <label style={{ display:'block', marginBottom:'0.5rem', fontWeight:'bold' }}>メールアドレス</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
              style={{ width:'100%', padding:'0.5rem', border:'1px solid #d1d5db', borderRadius:'4px', boxSizing:'border-box' }} />
          </div>
          <div style={{ marginBottom:'1.5rem' }}>
            <label style={{ display:'block', marginBottom:'0.5rem', fontWeight:'bold' }}>パスワード</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
              style={{ width:'100%', padding:'0.5rem', border:'1px solid #d1d5db', borderRadius:'4px', boxSizing:'border-box' }} />
          </div>
          {error && <div style={{ color:'#ef4444', marginBottom:'1rem', textAlign:'center' }}>{error}</div>}
          <button type="submit" disabled={loading}
            style={{ width:'100%', padding:'0.75rem', backgroundColor:'#3b82f6', color:'white', border:'none', borderRadius:'4px', cursor:'pointer', fontWeight:'bold', opacity: loading ? 0.7 : 1 }}>
            {loading ? 'ログイン中...' : 'ログイン'}
          </button>
        </form>
      </div>
    </div>
  )
}

export default Login
