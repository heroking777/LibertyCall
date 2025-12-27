import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer
} from 'recharts';
import { API_BASE } from '../config';

const API_BASE_URL = API_BASE; // 他のページと同様に /api を使用（プロキシ経由）

function AudioTestDashboard() {
  const [results, setResults] = useState(null);
  const [history, setHistory] = useState([]);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const wsRef = useRef(null);

  // 最新結果を取得
  const fetchLatestResults = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/audio_tests/latest`);
      setResults(response.data);
      setError(null);
    } catch (err) {
      if (err.response?.status === 404) {
        setError('ASR評価結果が見つかりません。先に音声テストを実行してください。');
      } else {
        setError(`エラー: ${err.message}`);
      }
    } finally {
      setLoading(false);
    }
  };

  // 履歴を取得
  const fetchHistory = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/audio_tests/history?limit=10`);
      setHistory(response.data.history || []);
    } catch (err) {
      console.error('履歴の取得に失敗:', err);
    }
  };

  // WebSocket接続
  useEffect(() => {
    // WebSocket URLを構築
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${API_BASE_URL}/audio_tests/ws/logs`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('WebSocket接続が開きました');
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'log') {
        setLogs(prev => [...prev.slice(-99), data.data]);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocketエラー:', error);
    };

    ws.onclose = () => {
      console.log('WebSocket接続が閉じました');
    };

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, []);

  // 初回データ取得
  useEffect(() => {
    fetchLatestResults();
    fetchHistory();

    // 5秒ごとに最新結果を更新
    const interval = setInterval(() => {
      fetchLatestResults();
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  // グラフ用データ準備
  const werHistoryData = history.map((item, index) => ({
    time: new Date(item.timestamp).toLocaleTimeString('ja-JP'),
    avgWER: item.summary?.avg_wer || 0,
    threshold: item.summary?.threshold || 0.1,
  }));

  const intentSuccessData = results?.results?.reduce((acc, item) => {
    // ファイル名からintentを推測（簡易版）
    const intent = item.file.includes('inquiry') ? 'INQUIRY' :
      item.file.includes('moshimoshi') ? 'GREETING' :
        item.file.includes('end') ? 'END_CALL' :
          item.file.includes('handoff') ? 'HANDOFF_REQUEST' : 'OTHER';

    if (!acc[intent]) {
      acc[intent] = { intent, pass: 0, fail: 0 };
    }
    if (item.status === 'PASS') {
      acc[intent].pass++;
    } else {
      acc[intent].fail++;
    }
    return acc;
  }, {}) || {};

  const intentChartData = Object.values(intentSuccessData);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-lg">読み込み中...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold mb-6">LibertyCall 音声テストダッシュボード</h1>

        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
            {error}
          </div>
        )}

        {/* ASR Summary */}
        {results && (
          <div className="bg-white rounded-lg shadow p-6 mb-6">
            <h2 className="text-xl font-semibold mb-4">📊 ASR 概要</h2>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <div className="text-sm text-gray-600">平均単語誤り率 (WER)</div>
                <div className={`text-2xl font-bold ${results.summary.avg_wer < results.summary.threshold
                    ? 'text-green-600' : 'text-red-600'
                  }`}>
                  {results.summary.avg_wer.toFixed(3)}
                  {results.summary.avg_wer < results.summary.threshold ? ' ✅' : ' ⚠️'}
                </div>
              </div>
              <div>
                <div className="text-sm text-gray-600">閾値</div>
                <div className="text-2xl font-bold">{results.summary.threshold.toFixed(3)}</div>
              </div>
              <div>
                <div className="text-sm text-gray-600">総サンプル数</div>
                <div className="text-2xl font-bold">{results.summary.total_samples}</div>
              </div>
            </div>
          </div>
        )}

        {/* Test Results Table */}
        {results && (
          <div className="bg-white rounded-lg shadow p-6 mb-6">
            <h2 className="text-xl font-semibold mb-4">🎧 テスト結果</h2>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      ファイル
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      期待される結果
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      認識結果
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      WER
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      結果
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {results.results.map((item, index) => (
                    <tr key={index}>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        {item.file}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {item.expected}
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500">
                        {item.recognized}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {item.wer.toFixed(3)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {item.status === 'PASS' ? (
                          <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-green-100 text-green-800">
                            ✅ 合格
                          </span>
                        ) : (
                          <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-red-100 text-red-800">
                            ⚠️ 不合格
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Charts */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* WER History Chart */}
          {werHistoryData.length > 0 && (
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-xl font-semibold mb-4">📈 WER 履歴</h2>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={werHistoryData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="avgWER" stroke="#8884d8" name="平均 WER" />
                  <Line type="monotone" dataKey="threshold" stroke="#82ca9d" name="閾値" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Intent Success Rate Chart */}
          {intentChartData.length > 0 && (
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-xl font-semibold mb-4">📊 意図認識成功率</h2>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={intentChartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="intent" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="pass" stackId="a" fill="#10b981" name="合格" />
                  <Bar dataKey="fail" stackId="a" fill="#ef4444" name="不合格" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Real-time Logs */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-semibold mb-4">📜 リアルタイムログ</h2>
          <div className="bg-gray-900 text-green-400 p-4 rounded font-mono text-sm h-64 overflow-y-auto">
            {logs.length === 0 ? (
              <div className="text-gray-500">ログを待機中...</div>
            ) : (
              logs.map((log, index) => (
                <div key={index} className="mb-1">{log}</div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default AudioTestDashboard;

