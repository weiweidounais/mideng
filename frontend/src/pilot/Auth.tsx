import { useState, type FormEvent } from 'react';
import type { Session } from './client';
import { request } from './client';
export default function Auth({ setup, onLogin }: {
    setup: boolean;
    onLogin: (s: Session) => void;
}) {
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    async function submit(e: FormEvent<HTMLFormElement>) {
        e.preventDefault();
        const form = e.currentTarget;
        const values = new FormData(form);
        setBusy(true);
        setError('');
        try {
            const s = await request<Session>(setup ? '/setup' : '/auth/login', { method: 'POST', body: JSON.stringify({ username: values.get('username'), password: values.get('password'), ...(setup ? { display_name: values.get('display_name') } : {}) }) });
            form.reset();
            onLogin(s);
        }
        catch (e) {
            setError(e instanceof Error ? e.message : '登录失败');
        }
        finally {
            setBusy(false);
        }
    }
    return <main className="auth-layout"><section className="auth-story"><div className="brand"><i />密灯 <span>嘉元项目协同中台</span></div><div><p className="eyebrow">让每一次交接，都有依据</p><h1>同一个项目，<br />同一份事实。</h1><p className="story-copy">把版本、责任和交付连在一起。<br />从独立账号与项目空间开始。</p></div><div className="scope-note">一期 · 内部试点 <span>本机脱敏数据</span></div></section><section className="auth-panel"><div className="auth-card"><span className="step-label">01 / 项目基础</span><h2>{setup ? '建立你的工作空间' : '欢迎回来'}</h2><p>{setup ? '在本机创建第一个管理员账号，之后为同事配置独立账号和项目岗位。' : '使用你的独立账号登录，查看被授权的项目。'}</p>{error && <div className="notice error" role="alert">{error}</div>}<form onSubmit={e => void submit(e)}>{setup && <label>姓名<input name="display_name" autoComplete="name" maxLength={80} required placeholder="你的姓名"/></label>}<label>账号<input name="username" autoComplete="username" required placeholder="字母、数字或下划线"/></label><label>密码<input name="password" type="password" autoComplete={setup ? 'new-password' : 'current-password'} minLength={setup ? 6 : 1} maxLength={128} required placeholder={setup ? '至少 6 位' : '输入密码'}/></label><button className="primary" disabled={busy}>{busy ? '正在验证…' : setup ? '创建管理员并进入' : '登录工作空间'} <span>→</span></button></form><p className="fine">{setup ? '首次设置完成后入口自动关闭。请妥善保存密码。' : '岗位和项目权限由管理员配置，切换页面不会改变权限。'}</p></div></section></main>;
}
