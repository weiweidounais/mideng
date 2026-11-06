import '@ant-design/v5-patch-for-react-19';
import React from 'react';
import {createRoot} from 'react-dom/client';
import DemoApp from './demo/DemoApp';
import './pilot/styles.css';
import './demo/demo.css';
createRoot(document.getElementById('root')!).render(<React.StrictMode><DemoApp/></React.StrictMode>);
