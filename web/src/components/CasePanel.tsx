import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type AlertDetail, type CopilotAnswer } from "../lib/api";
import { KIND_LABEL, SEVERITY_LABEL, coord, hoursBetween, utcTime } from "../lib/vocab";
import { Glyph } from "./Glyph";
import { SarChip } from "./SarChip";

const store = {
  get(k: string) {
    try { return sessionStorage.getItem(k) ?? ""; } catch { return ""; }
  },
  set(k: string, v: string) {
    try { sessionStorage.setItem(k, v); } catch { /* private mode: keep it in memory only */ }
  },
};

function evidenceRows(a: AlertDetail, names: Map<string, string>): [string, string][] {
  const e = a.evidence;
  const rows: [string, string][] = [];
  const name = (m: string) => `${names.get(m) ?? "Unknown"} (${m})`;
  if (e.gap_hours != null) rows.push(["Silent for", `${e.gap_hours} h`]);
  if (e.last_fix) rows.push(["Last fix before silence", `${utcTime(e.last_fix.ts)}`]);
  if (e.next_fix) rows.push(["First fix after", `${utcTime(e.next_fix.ts)}`]);
  if (e.distance_km != null) rows.push(["Moved while silent", `${e.distance_km} km (needs only ${e.implied_knots} kn)`]);
  if (e.largest_jump_km != null) rows.push(["Largest jump", `${e.largest_jump_km} km, ${e.jumps} jumps in total`]);
  if (e.other_mmsi) rows.push(["Alongside", name(e.other_mmsi)]);
  if (e.hours != null) rows.push(["Time together", `${e.hours} h, closest ${e.min_distance_km} km`]);
  if (e.fishing_hours != null) rows.push(["Fishing-speed time", `${e.fishing_hours} h on the ${e.coast} coast`]);
  if (e.warning_lead_minutes != null) {
    rows.push(["Closest to the IMBL", `${e.min_distance_km} km`]);
    rows.push(["Time a warning would have given", `${e.warning_lead_minutes} min`]);
  }
  if (e.length_m != null) rows.push(["Radar return", `${e.length_m} m long, confidence ${e.confidence}`]);
  if (e.imbl_km != null) rows.push(["Distance to IMBL", `${e.imbl_km} km`]);
  if (e.possible_identity) {
    const p = e.possible_identity;
    rows.push(["Could be", `${name(p.mmsi)}, ${p.km_from_expected_path} km off its silent track`]);
  }
  if (e.zones?.length || e.zone) rows.push(["Protected area", "Gulf of Mannar Marine National Park"]);
  return rows;
}

interface Props {
  alert: AlertDetail;
  names: Map<string, string>;
  onClose: () => void;
}

export function CasePanel({ alert: a, names, onClose }: Props) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [token, setToken] = useState(() => store.get("gw-token"));
  const [analyst, setAnalyst] = useState(() => store.get("gw-analyst"));
  const [askToken, setAskToken] = useState(false);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<CopilotAnswer | null>(null);

  const review = useMutation({
    mutationFn: (action: "escalate" | "dismiss" | "reopen") => api.review(a.id, action, note, token, analyst),
    onSuccess: () => {
      setNote("");
      qc.invalidateQueries({ queryKey: ["alerts"] });
      qc.invalidateQueries({ queryKey: ["alert", a.id] });
    },
  });

  const ask = useMutation({
    mutationFn: (q: string) => api.ask(q, a.id),
    onSuccess: setAnswer,
  });

  const act = (action: "escalate" | "dismiss" | "reopen") => {
    if (!token) return setAskToken(true);
    review.mutate(action);
  };

  const total = a.contributions.reduce((s, c) => s + c.points, 0) || 1;
  const vesselName = a.vessel?.name ?? (a.mmsi ? a.mmsi : "Unidentified vessel");

  return (
    <article className={`case cat-${a.category}`} aria-labelledby="case-title">
      <header className="case-head">
        <button className="case-close" onClick={onClose} aria-label="Close case">Close</button>
        <p className={`case-kind sev-${a.severity}`}>
          <Glyph kind={a.kind} size={16} /> {KIND_LABEL[a.kind] ?? a.kind}
          <span className="case-sev">{SEVERITY_LABEL[a.severity]}</span>
        </p>
        <h2 id="case-title" className="vessel-name">{vesselName}</h2>
        {a.vessel ? (
          <p className="case-meta">
            MMSI {a.vessel.mmsi}, flag {a.vessel.flag === "--" ? "not reported" : a.vessel.flag}, {a.vessel.type}, {Math.round(a.vessel.length_m)} m
          </p>
        ) : (
          <p className="case-meta">No AIS identity. Seen only on radar.</p>
        )}
        <p className={`status status-${a.status}`}>
          {a.status === "open" ? "Waiting for review" : a.status === "escalated" ? "Escalated" : "Dismissed"}
        </p>
      </header>

      <section className="case-block">
        <p className="case-summary">{a.summary}.</p>
        <p className="case-fine">
          {utcTime(a.start)}
          {hoursBetween(a.start, a.end) > 0.05 && <> to {utcTime(a.end)}</>}
          <br />
          {coord(a.lat, a.lon)}
        </p>
      </section>

      <section className="case-block">
        <h3>Why it scored {Math.round(a.score)}</h3>
        <ul className="ledger">
          {a.contributions.map((c) => (
            <li key={c.reason}>
              <span className="ledger-bar" style={{ width: `${(c.points / total) * 100}%` }} />
              <span className="ledger-reason">{c.reason}</span>
              <span className="ledger-pts">+{c.points}</span>
            </li>
          ))}
        </ul>
      </section>

      {a.detection && (
        <section className="case-block">
          <h3>Radar</h3>
          <SarChip detectionId={a.detection.id} lengthM={a.detection.length_m} />
        </section>
      )}

      <section className="case-block">
        <h3>Evidence</h3>
        <dl className="facts">
          {evidenceRows(a, names).map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      </section>

      <section className="case-block decide">
        <h3>Decision</h3>
        <label className="field">
          <span>Note for the record</span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder={a.category === "safety" ? "Who was contacted, and how" : "What you checked and what you decided"}
          />
        </label>
        <div className="actions">
          {a.status !== "escalated" && (
            <button className="btn btn-primary" onClick={() => act("escalate")} disabled={review.isPending}>Escalate</button>
          )}
          {a.status !== "dismissed" && (
            <button className="btn" onClick={() => act("dismiss")} disabled={review.isPending}>Dismiss</button>
          )}
          {a.status !== "open" && (
            <button className="btn" onClick={() => act("reopen")} disabled={review.isPending}>Reopen</button>
          )}
          <a className="btn btn-quiet" href={api.reportUrl(a.id)} target="_blank" rel="noreferrer">Open case file</a>
        </div>
        {review.isError && <p className="error">{(review.error as Error).message}</p>}

        {askToken && (
          <form
            className="token-form"
            onSubmit={(e) => {
              e.preventDefault();
              store.set("gw-token", token);
              store.set("gw-analyst", analyst);
              setAskToken(false);
            }}
          >
            <p>Reviewing needs the analyst token set on the server (GW_ANALYST_TOKEN).</p>
            <label className="field"><span>Your name</span>
              <input value={analyst} onChange={(e) => setAnalyst(e.target.value)} autoComplete="name" />
            </label>
            <label className="field"><span>Analyst token</span>
              <input value={token} onChange={(e) => setToken(e.target.value)} type="password" autoComplete="off" />
            </label>
            <button className="btn btn-primary" type="submit" disabled={!token}>Save for this session</button>
          </form>
        )}

        {a.reviews.length > 0 && (
          <ol className="history">
            {a.reviews.map((r, i) => (
              <li key={i}>
                <strong>{r.action === "escalate" ? "Escalated" : r.action === "dismiss" ? "Dismissed" : "Reopened"}</strong> by {r.analyst}, {utcTime(r.ts)}
                {r.note && <q>{r.note}</q>}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="case-block">
        <h3>Ask about this case</h3>
        <form
          className="ask"
          onSubmit={(e) => {
            e.preventDefault();
            if (question.trim().length > 1) ask.mutate(question.trim());
          }}
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Brief me on this, or ask about the vessel"
            aria-label="Question for the copilot"
          />
          <button className="btn" disabled={ask.isPending}>{ask.isPending ? "Thinking" : "Ask"}</button>
        </form>
        <div className="ask-suggest">
          <button onClick={() => ask.mutate("Brief me on this alert")}>Brief me</button>
          {a.mmsi && <button onClick={() => ask.mutate(`What else do we know about ${a.mmsi}?`)}>Vessel history</button>}
        </div>
        {ask.isError && <p className="error">{(ask.error as Error).message}</p>}
        {answer && (
          <div className="answer">
            <p>{answer.answer}</p>
            {answer.checks.unverified_numbers.length > 0 && (
              <p className="warn">
                These figures do not appear in the data the copilot looked at: {answer.checks.unverified_numbers.join(", ")}.
                Check them before you rely on this answer.
              </p>
            )}
            <p className="answer-trace">
              {answer.mode === "guardrail"
                ? "Read-only copilot. No tools were called."
                : `Looked up ${answer.tool_calls.map((c) => c.tool.replace(/_/g, " ")).join(", ") || "nothing"} (${answer.mode === "llm" ? "language model" : "offline writer"})`}
              {answer.note && <> {answer.note}</>}
            </p>
          </div>
        )}
      </section>

      <details className="case-block lineage">
        <summary>Where this came from</summary>
        <dl className="facts">
          <div><dt>Rule</dt><dd>{a.lineage.rule}</dd></div>
          <div><dt>Pipeline run</dt><dd>{a.lineage.run_id}, version {a.lineage.pipeline_version}</dd></div>
          {a.lineage.sources.map((s, i) => (
            <div key={i}>
              <dt>{s.type === "ais" ? "AIS track" : s.type === "sar_detection" ? "Radar detection" : "Linked alert"}</dt>
              <dd>{s.type === "ais" ? `${s.mmsi}, ${utcTime(s.window[0])} onward` : s.type === "sar_detection" ? `${s.detection_id} (${s.mission})` : s.alert_id}</dd>
            </div>
          ))}
          <div><dt>Cleaning on that run</dt><dd>
            {a.lineage.cleaning.rows_in} rows in, {a.lineage.cleaning.duplicates} duplicates and {a.lineage.cleaning.bad_position} bad positions removed
          </dd></div>
          <div><dt>Thresholds</dt><dd>
            gap {a.lineage.thresholds.gap_hours} h, spoof {a.lineage.thresholds.spoof_knots} kn, IMBL warning {a.lineage.thresholds.imbl_warn_km} km, radar match {a.lineage.thresholds.match_gate_km} km
          </dd></div>
        </dl>
      </details>
    </article>
  );
}
