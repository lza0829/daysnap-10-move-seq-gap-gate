import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function 周期快照() {
  const [日, set日] = useState("");
  const [含旁置, set含旁置] = useState(true);
  const [行, set行] = useState([]);
  const [讯, set讯] = useState("");

  const 刷新 = () => {
    const p = new URLSearchParams();
    if (日) p.append("营业日", 日);
    p.append("状态", 含旁置 ? "全部" : "有效");
    return api.快照(`?${p.toString()}`).then(set行);
  };

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [含旁置]);

  const 晋升 = (r) =>
    api
      .晋升(r.账户键, r.营业日)
      .then((p) => set讯(`已晋升 ${r.账户键} ${r.营业日}，正确余额=${p.余额}`))
      .then(刷新)
      .catch((e) => set讯("晋升被拒：" + String(e.message || e)));

  return (
    <div>
      <h1 className="题">周期快照 · 正式镜与旁置镜</h1>
      <p className="述">
        每个账户每个营业日一行。「有效」才是回放权威；序缺口抽取产生的「旁置」镜余额可能是残缺净额，
        仅供可读与晋升核对，绝不能当有效通过。
      </p>
      <div className="行">
        <input value={日} onChange={(e) => set日(e.target.value)} placeholder="筛选营业日，可空" />
        <label style={{ display: "flex", gap: "0.35rem", alignItems: "center", fontSize: "0.88rem" }}>
          <input type="checkbox" checked={含旁置} onChange={(e) => set含旁置(e.target.checked)} />
          显示旁置镜
        </label>
        <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>刷新</button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}
      {!行.length ? (
        <div className="空态">暂无快照</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>账户键</th><th>营业日</th><th>余额</th><th>状态</th>
              <th>抽取批次</th><th>来源</th><th>动作</th>
            </tr>
          </thead>
          <tbody>
            {行.map((r) => (
              <tr key={r.快照键} style={r.状态 === "旁置" ? { background: "var(--焰弱)" } : undefined}>
                <td>{r.账户键}</td>
                <td>{r.营业日}</td>
                <td style={{ fontVariantNumeric: "tabular-nums" }}>{r.余额}</td>
                <td>
                  {r.状态 === "有效" ? (
                    <span className="徽章 通">有效</span>
                  ) : r.状态 === "旁置" ? (
                    <span className="徽章 旁">旁置·非有效</span>
                  ) : (
                    <span className="徽章 灰">{r.状态}</span>
                  )}
                </td>
                <td>{r.抽取批次编号}</td>
                <td>{r.来源}</td>
                <td>
                  {r.状态 === "旁置" ? (
                    <button onClick={() => 晋升(r)}>补序后晋升</button>
                  ) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
