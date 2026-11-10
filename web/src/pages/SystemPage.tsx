import { useCallback, useEffect, useState } from "react";

import { userMessage } from "../api/client";
import { getHealth, getMetrics } from "../api/observability";
import type { HealthResponse, MetricsSnapshot } from "../api/types";
import { StatusBadge } from "../components/StatusBadge";

export function SystemPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [healthPayload, metricsPayload] = await Promise.all([
        getHealth(),
        getMetrics(),
      ]);
      setHealth(healthPayload);
      setMetrics(metricsPayload);
      setError(null);
    } catch (requestError: unknown) {
      setError(userMessage(requestError));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">LOCAL OBSERVABILITY</p>
          <h1>系统状态</h1>
          <p className="lede">本地开发状态、进程内指标和能力边界。</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => void refresh()}>
          刷新状态
        </button>
      </header>

      {error ? <p className="notice notice-error">{error}</p> : null}

      <section className="card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">HEALTH</p>
            <h2>后端健康检查</h2>
          </div>
          <StatusBadge value={health ? "success" : "error"} kind="result" />
        </div>
        {health ? (
          <div className="stat-row">
            <div>
              <span>服务</span>
              <strong>{health.service}</strong>
            </div>
            <div>
              <span>版本</span>
              <strong>{health.version}</strong>
            </div>
            <div>
              <span>状态</span>
              <strong>正常</strong>
            </div>
          </div>
        ) : (
          <p className="empty-state">后端服务不可用或尚未检查。</p>
        )}
      </section>

      <section className="card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">METRICS</p>
            <h2>进程内指标</h2>
          </div>
          {metrics ? (
            <span className="muted">{metrics.generated_at}</span>
          ) : null}
        </div>
        {metrics ? (
          <>
            <div className="stat-row">
              <div>
                <span>总请求</span>
                <strong>{metrics.requests_total}</strong>
              </div>
              <div>
                <span>Agent 流式</span>
                <strong>{metrics.agent_stream.requests_total}</strong>
              </div>
              <div>
                <span>流式成功</span>
                <strong>{metrics.agent_stream.answered_total}</strong>
              </div>
              <div>
                <span>流式拒答</span>
                <strong>{metrics.agent_stream.refused_total}</strong>
              </div>
              <div>
                <span>流式错误</span>
                <strong>{metrics.agent_stream.errors_total}</strong>
              </div>
            </div>
            <div className="stat-row">
              <div>
                <span>LLM 调用</span>
                <strong>{metrics.llm.calls_total}</strong>
              </div>
              <div>
                <span>LLM 流式</span>
                <strong>{metrics.llm.stream_calls_total}</strong>
              </div>
              <div>
                <span>LLM 错误</span>
                <strong>{metrics.llm.errors_total}</strong>
              </div>
              <div>
                <span>平均流式耗时</span>
                <strong>
                  {metrics.agent_stream.average_duration_ms.toFixed(1)} ms
                </strong>
              </div>
            </div>
          </>
        ) : (
          <p className="empty-state">指标暂不可用。</p>
        )}
        <p className="hint">
          指标仅保存在进程内，重启服务后归零；metrics 接口默认无认证，仅适合本地开发。
        </p>
      </section>

      <section className="card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">SCOPE</p>
            <h2>能力与限制</h2>
          </div>
        </div>
        <div className="two-column-list">
          <section>
            <h3>已支持</h3>
            <ul className="check-list">
              <li>本地 PDF 知识库</li>
              <li>页码级引用与 PDF 预览</li>
              <li>无证据拒答</li>
              <li>一次改写、一次二次检索</li>
              <li>受控科研工具</li>
              <li>SSE 流式回答与基础指标</li>
              <li>小规模本地评测</li>
            </ul>
          </section>
          <section>
            <h3>已知限制</h3>
            <ul className="cross-list">
              <li>不支持 OCR</li>
              <li>不支持多轮对话</li>
              <li>不支持生产级鉴权</li>
              <li>Metrics 重启后归零</li>
              <li>真实 Ollama 流式端到端未验证</li>
              <li>真实论文语料评测未完成</li>
              <li>Docker 最新镜像需重新构建验证</li>
            </ul>
          </section>
        </div>
      </section>
    </div>
  );
}
