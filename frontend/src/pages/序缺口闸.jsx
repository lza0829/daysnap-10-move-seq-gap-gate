import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

function 卡({ k, v, 态 }) {
  return (
    <div className={`格 ${态 || ""}`}>
      <div className="k">{k}</div>
      <div className="v">{typeof v === "boolean" ? String(v) : v}</div>
    </div>
  );
}

export default function 序缺口闸() {
  const [户, set户] = useState("户甲");
  const [日, set日] = useState("2026-11-20");
  const [v, setV] = useState(null);
  const [regs, setRegs] = useState([]);
  const [policy, setPolicy] = useState("");
  const [msg, setMsg] = useState("");

  const 刷新核证 = useCallback(
    () => api.核证序缺口(户, 日).then(setV).catch((e) => setMsg(String(e.message || e))),
    [户, 日]
  );
  const 刷新登记 = useCallback(() => api.序缺口列表().then(setRegs).catch(() => {}), []);
  const 刷新口径 = useCallback(() => api.口径().then((r) => setPolicy(r.口径)).catch(() => {}), []);

  useEffect(() => {
    刷新核证();
    刷新登记();
    刷新口径();
  }, [刷新核证, 刷新登记, 刷新口径]);

  const 包 = (p) =>
    p
      .then((r) => {
        if (r && typeof r === "object") setMsg(JSON.stringify(r));
      })
      .then(() => 刷新核证())
      .then(刷新登记)
      .catch((e) => setMsg("失败闭：" + String(e.message || e)));

  return (
    <div>
      <h1 className="题">序缺口闸 · 核证 / 旁置 / 晋升</h1>
      <p className="述">
        核证接口必须说清四件事：缺口区间、旁置有无、可否晋升、valid。当前全局口径：
        <b> {policy || "…"}</b>（出厂为「旁置日终镜」；另一口径「登记阻塞」可整库切换，同一时刻只贯彻一种）。
      </p>

      <div className="行">
        <input value={户} onChange={(e) => set户(e.target.value)} placeholder="账户键" style={{ width: 140 }} />
        <input value={日} onChange={(e) => set日(e.target.value)} placeholder="YYYY-MM-DD" style={{ width: 150 }} />
        <button className="水" onClick={() => 包(刷新核证())}>核证</button>
        <select
          value={policy}
          onChange={(e) => setPolicy(e.target.value)}
          title="全局口径"
        >
          <option value="旁置日终镜">旁置日终镜（乙）</option>
          <option value="登记阻塞">登记阻塞（甲）</option>
        </select>
        <button
          className="次"
          onClick={() => api.设口径(policy).then((r) => setMsg("口径已切：" + r.口径)).catch((e) => setMsg(String(e.message)))}
        >
          应用口径
        </button>
      </div>

      <div className="行">
        <button className="次" onClick={() => 包(api.装载夹具("序缺口_缺号样例.json"))}>① 装序号1·3缺2</button>
        <button onClick={() => 包(api.抽取(日))}>② 日终抽取</button>
        <button className="水" onClick={() => 包(api.回放(日))}>③ 全量回放</button>
        <button className="次" onClick={() => 包(api.装载夹具("序缺口_补2样例.json"))}>④ 补序号2</button>
        <button
          onClick={() => 包(api.晋升(户, 日))}
          disabled={v && !v.可否晋升}
          style={v && !v.可否晋升 ? { opacity: 0.5, cursor: "not-allowed" } : undefined}
        >
          ⑤ 晋升旁置→正式
        </button>
      </div>
      {msg ? <p className="讯" style={{ wordBreak: "break-all" }}>{msg}</p> : null}

      {v ? (
        <div className="核证格">
          <卡 k="缺口区间" v={JSON.stringify(v.缺口区间)} 态={v.缺口区间 && v.缺口区间.length ? "坏" : "好"} />
          <卡 k="旁置有无" v={v.旁置有无 ? "true" : "false"} 态={v.旁置有无 ? "警" : ""} />
          <卡 k="可否晋升" v={v.可否晋升 ? "true" : "false"} 态={v.可否晋升 ? "好" : ""} />
          <卡 k="valid" v={v.valid ? "true" : "false"} 态={v.valid ? "好" : "坏"} />
          <卡 k="序号轨" v={v.序号轨 ? "在轨" : "无"} />
          <卡 k="连续" v={v.连续 ? "true" : "false"} 态={v.连续 ? "好" : "坏"} />
          <卡 k="正式有无" v={v.正式有无 ? `true (${v.正式余额})` : "false（空）"} 态={v.正式有无 ? "好" : "坏"} />
          <卡 k="旁置余额" v={v.旁置余额 ?? "—"} 态="警" />
        </div>
      ) : (
        <div className="空态">输入账户与营业日后核证</div>
      )}

      <div className="段">
        <h2 className="段题">序缺口登记</h2>
        {!regs.length ? (
          <div className="空态">无缺口登记</div>
        ) : (
          <table>
            <thead>
              <tr><th>账户</th><th>营业日</th><th>缺口区间</th><th>状态</th><th>口径</th><th>旁置快照键</th><th>检出批次</th><th>时刻</th></tr>
            </thead>
            <tbody>
              {regs.map((r) => (
                <tr key={r.编号}>
                  <td>{r.账户键}</td>
                  <td>{r.营业日 || "—"}</td>
                  <td>{JSON.stringify(r.缺口区间)}</td>
                  <td>
                    {r.状态 === "未解除" ? <span className="徽章 败">{r.状态}</span>
                      : r.状态 === "已晋升" ? <span className="徽章 通">{r.状态}</span>
                      : <span className="徽章 旁">{r.状态}</span>}
                  </td>
                  <td>{r.口径}</td>
                  <td>{r.旁置快照键 || "—"}</td>
                  <td>{r.检出批次编号}</td>
                  <td>{r.时刻}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
