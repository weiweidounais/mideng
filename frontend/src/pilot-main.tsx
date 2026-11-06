import '@ant-design/v5-patch-for-react-19';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './pilot/App';
import './pilot/styles.css';
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#14786c', borderRadius: 8, fontFamily: '-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif' } }}><App /></ConfigProvider></React.StrictMode>);
