import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function 旁置簿() {
  const [行, set行] = useState([]);
  const [镜, set镜] = useState([]);
  const [核, set核] = useState({});
  const [讯, set讯] = useState("");

  const 刷新 = async () => {
    const [raw, side] = await Promise.all([api.旁置(), api.旁置日终()]);
    set行(raw);
    set镜(side);
    const map = {};
    await Promise.all(
      side.map(async (s) => {
        try {
          map[`${s.账户键}|${s.营业日}`] = await api.核证序缺口(s.账户键, s.营业日);
        } catch {
          /* ignore */
        }
      })
    );
    set核(map);
  };

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
  }, []);

  const 晋升 = (s) =>
    api
      .晋升(s.账户键, s.营业日)
      .then((r) => set讯(`已晋升 ${s.账户键} ${s.营业日}：正确余额=${r.余额}（${r.动作}），回放权威已恢复`))
      .then(刷新)
      .catch((e) => set讯("晋升被拒（失败闭）：" + String(e.message || e)));

  return (
    <div>
      <h1 className="题">旁置簿 · 旁置日终镜</h1>
      <p className="述">
        上半是序缺口专用的「旁置日终镜」：状态为旁置、<b>非有效、不得作为回放权威</b>；
        补序使缺口闭合后，须点「晋升」按全量流水重算并转为正式有效镜。下半是未知账户/字段非法等原始旁置载荷。
      </p>
      <div className="行">
        <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>刷新</button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}

      <div className="段">
        <h2 className="段题">旁置日终镜（序缺口）</h2>
        {!镜.length ? (
          <div className="空态">无旁置日终镜</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>账户</th><th>营业日</th><th>旁置余额</th><th>开端</th><th>流水净额</th>
                <th>登记缺口</th><th>状态</th><th> live 核证</th><th>动作</th>
              </tr>
            </thead>
            <tbody>
              {镜.map((s) => {
                const v = 核[`${s.账户键}|${s.营业日}`];
                const 可晋 = v ? v.可否晋升 : false;
                return (
                  <tr key={s.快照键}>
                    <td>{s.账户键}</td>
                    <td>{s.营业日}</td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>{s.余额}</td>
                    <td>{s.开端余额}</td>
                    <td>{s.流水净额}</td>
                    <td>{JSON.stringify(s.缺口区间)}</td>
                    <td>
                      {s.状态 === "旁置" ? (
                        <span className="徽章 旁">旁置·非权威</span>
                      ) : (
                        <span className="徽章 通">{s.状态}</span>
                      )}
                    </td>
                    <td>
                      {v ? (
                        v.valid ? (
                          <span className="徽章 通">valid</span>
                        ) : 可晋 ? (
                          <span className="徽章 旁">缺口已补·可晋升</span>
                        ) : (
                          <span className="徽章 败">缺口未补·不可晋</span>
                        )
                      ) : "—"}
                    </td>
                    <td>
                      {s.状态 === "旁置" ? (
                        <button disabled={v && !可晋} onClick={() => 晋升(s)}
                          style={v && !可晋 ? { opacity: 0.5, cursor: "not-allowed" } : undefined}>
                          晋升正式
                        </button>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="段">
        <h2 className="段题">原始旁置载荷（旁置簿）</h2>
        {!行.length ? <div className="空态">旁置为空</div> : (
          <table>
            <thead><tr><th>原因</th><th>账户键</th><th>营业日</th><th>载荷</th><th>时刻</th></tr></thead>
            <tbody>
              {行.map((r) => (
                <tr key={r.编号}>
                  <td>{r.原因}</td><td>{r.账户键 || "—"}</td><td>{r.营业日 || "—"}</td>
                  <td style={{ maxWidth: 360, wordBreak: "break-all" }}>{r.载荷}</td><td>{r.时刻}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
