import {Component, type ReactNode} from 'react';

// A stale tab can request an old lazy chunk after a frontend rebuild.
export class RecoveryBoundary extends Component<{children: ReactNode}, {failed: boolean}> {
  state = {failed: false};
  static getDerivedStateFromError() { return {failed: true}; }
  render() {
    if (this.state.failed) return <div className="empty-state" role="alert">
      <h2>页面加载失败</h2><p>服务可能刚刚更新，刷新可重新加载最新页面。</p>
      <button onClick={() => window.location.reload()}>刷新页面</button>
    </div>;
    return this.props.children;
  }
}
