import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

export default function 日终抽取() {
  const [日, set日] = useState("2026-11-20");
  const [批, set批] = useState([]);
  const [讯, set讯] = useState("");
  const [末报, set末报] = useState(null);

  const 刷新 = () => api.抽取批次().then(set批);

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
  }, []);

  const 跑 = () =>
    api
      .抽取(日)
      .then((r) => {
        set末报(r);
        set讯(
          `批次 ${r.批次编号} 正式写入=${r.写入} 盖写=${r.盖写} 旁置日终=${r.旁置日终 ?? 0} ` +
            `序缺口=${r.序缺口 ?? 0} 全有效=${r.全有效 ?? r.通过}`
        );
      })
      .then(刷新)
      .catch((e) => set讯(String(e.message || e)));

  return (
    <div>
      <h1 className="题">日终抽取 · 序缺口闸</h1>
      <p className="述">
        按营业日写周期快照：前日有效余额 + 当日流水净额。有序号轨且存在缺号/重号的户，
        禁止写有效正式镜——乙口径只写「旁置」日终镜待晋升，完整户照常抽取，多户批次如实判失败。
      </p>
      <div className="行">
        <input value={日} onChange={(e) => set日(e.target.value)} placeholder="YYYY-MM-DD" />
        <button onClick={跑}>执行抽取</button>
        <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>刷新批次</button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}

      {末报 && (末报.序缺口 > 0 || 末报.旁置日终 > 0) ? (
        <div className="提示条">
          本批 {末报.序缺口} 户有序缺口，整批 全有效={String(末报.全有效)}；残缺净额只进旁置镜，
          不会成为有效正式镜。前往 <Link to="/旁置簿">旁置簿</Link> 晋升，或在{" "}
          <Link to="/序缺口闸">序缺口闸</Link> 核证。
          {Array.isArray(末报.缺口账户) && 末报.缺口账户.length ? (
            <ul style={{ margin: "0.4rem 0 0", paddingLeft: "1.1rem" }}>
              {末报.缺口账户.map((g, i) => (
                <li key={i}>
                  {g.账户键}：缺口 {JSON.stringify(g.缺口区间)} → {g.处置}
                  {typeof g.残缺净额 === "number" ? `（残缺净额 ${g.残缺净额}）` : ""}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="段">
        <h2 className="段题">抽取批次</h2>
        {!批.length ? (
          <div className="空态">尚无抽取</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>编号</th>
                <th>营业日</th>
                <th>时刻</th>
                <th>报告</th>
              </tr>
            </thead>
            <tbody>
              {批.map((r) => (
                <tr key={r.编号}>
                  <td>{r.编号}</td>
                  <td>{r.营业日}</td>
                  <td>{r.时刻}</td>
                  <td>{typeof r.报告 === "object" ? JSON.stringify(r.报告) : r.报告}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
